import asyncio
import hashlib
import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any, AsyncIterable, Dict, List, Optional, Tuple

from bidict import bidict

from hummingbot.connector.constants import s_decimal_NaN
from hummingbot.connector.derivative.derive_perpetual import (
    derive_perpetual_constants as CONSTANTS,
    derive_perpetual_web_utils as web_utils,
)
from hummingbot.connector.derivative.derive_perpetual.derive_perpetual_api_order_book_data_source import (
    DerivePerpetualAPIOrderBookDataSource,
)
from hummingbot.connector.derivative.derive_perpetual.derive_perpetual_api_user_stream_data_source import (
    DerivePerpetualAPIUserStreamDataSource,
)
from hummingbot.connector.derivative.derive_perpetual.derive_perpetual_auth import DerivePerpetualAuth
from hummingbot.connector.derivative.position import Position
from hummingbot.connector.perpetual_derivative_py_base import PerpetualDerivativePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.connector.utils import combine_to_hb_trading_pair, get_new_client_order_id
from hummingbot.core.api_throttler.data_types import RateLimit
from hummingbot.core.data_type.common import OrderType, PositionAction, PositionMode, PositionSide, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderUpdate, TradeUpdate
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.data_type.trade_fee import TokenAmount, TradeFeeBase
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.utils.async_utils import safe_ensure_future, safe_gather
from hummingbot.core.utils.estimate_fee import build_trade_fee
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory

if TYPE_CHECKING:
    from hummingbot.client.config.config_helpers import ClientConfigAdapter


class DerivePerpetualDerivative(PerpetualDerivativePyBase):
    web_utils = web_utils

    SHORT_POLL_INTERVAL = 5.0
    LONG_POLL_INTERVAL = 12.0

    def __init__(
            self,
            client_config_map: "ClientConfigAdapter",
            derive_perpetual_api_secret: str = None,
            sub_id: int = None,
            derive_perpetual_api_key: str = None,
            trading_pairs: Optional[List[str]] = None,
            trading_required: bool = True,
            domain: str = CONSTANTS.DEFAULT_DOMAIN,
    ):
        self.derive_perpetual_api_key = derive_perpetual_api_key
        self.derive_perpetual_secret_key = derive_perpetual_api_secret
        self._sub_id = sub_id
        self._trading_required = trading_required
        self._trading_pairs = trading_pairs
        self._domain = domain
        self._position_mode = None
        self._last_trade_history_timestamp = None
        self._last_trades_poll_timestamp = 1.0
        self._instrument_ticker = []
        self.real_time_balance_update = False
        self.currencies = []
        super().__init__(client_config_map)

    @property
    def name(self) -> str:
        # Note: domain here refers to the entire exchange name. i.e. derive_perpetual_ or derive_perpetual_testnet
        return self._domain

    @staticmethod
    def derive_perpetual_order_type(order_type: OrderType) -> str:
        return order_type.name.lower()

    @property
    def authenticator(self) -> DerivePerpetualAuth:
        return DerivePerpetualAuth(self.derive_perpetual_api_key, self.derive_perpetual_secret_key, self._sub_id, self._trading_required)

    @property
    def rate_limits_rules(self) -> List[RateLimit]:
        return CONSTANTS.RATE_LIMITS

    @property
    def domain(self) -> str:
        return self._domain

    @property
    def client_order_id_max_length(self) -> int:
        return CONSTANTS.MAX_ORDER_ID_LEN

    @property
    def client_order_id_prefix(self) -> str:
        return CONSTANTS.BROKER_ID

    @property
    def trading_rules_request_path(self) -> str:
        return CONSTANTS.EXCHANGE_INFO_PATH_URL

    @property
    def trading_pairs_request_path(self) -> str:
        return CONSTANTS.EXCHANGE_INFO_PATH_URL

    @property
    def trading_currencies_request_path(self) -> str:
        return CONSTANTS.EXCHANGE_CURRENCIES_PATH_URL

    @property
    def check_network_request_path(self) -> str:
        return CONSTANTS.PING_PATH_URL

    @property
    def trading_pairs(self):
        return self._trading_pairs

    @property
    def is_cancel_request_in_exchange_synchronous(self) -> bool:
        return True

    @property
    def is_trading_required(self) -> bool:
        return self._trading_required

    @property
    def funding_fee_poll_interval(self) -> int:
        return 120

    async def _make_network_check_request(self):
        await self._api_get(path_url=self.check_network_request_path)

    def supported_order_types(self) -> List[OrderType]:
        """
        :return a list of OrderType supported by this connector
        """
        return [OrderType.LIMIT, OrderType.LIMIT_MAKER, OrderType.MARKET]

    def supported_position_modes(self):
        """
        This method needs to be overridden to provide the accurate information depending on the exchange.
        """
        return [PositionMode.ONEWAY]

    def get_buy_collateral_token(self, trading_pair: str) -> str:
        trading_rule: TradingRule = self._trading_rules[trading_pair]
        return trading_rule.buy_order_collateral_token

    def get_sell_collateral_token(self, trading_pair: str) -> str:
        trading_rule: TradingRule = self._trading_rules[trading_pair]
        return trading_rule.sell_order_collateral_token

    async def _make_trading_pairs_request(self) -> Any:
        exchange_infos = []
        if len(self.currencies) == 0:
            self.currencies.append(await self._make_currency_request())
        for currency in self.currencies[0]["result"]:

            payload = {
                "expired": True,
                "instrument_type": "perp",
                "currency": currency["currency"],
            }

            exchange_info = await self._api_post(path_url=self.trading_currencies_request_path, data=payload)
            if "error" in exchange_info:
                if 'Instrument not found' in exchange_info['error']['message']:
                    self.logger().debug(f"Ignoring currency {currency['currency']}: not supported sport.")
                    continue
                self.logger().error(f"Error: {currency['message']}")
                raise
            exchange_infos.append(exchange_info["result"]["instruments"][0])
        return exchange_infos

    async def _make_currency_request(self) -> Any:
        currencies = await self._api_post(path_url=self.trading_pairs_request_path, data={
            "instrument_type": "parp",
        })
        self.currencies.append(currencies)
        return currencies

    async def _make_trading_rules_request(self) -> Any:
        self._instrument_ticker = []
        if len(self.currencies) == 0:
            self.currencies.append(await self._make_currency_request())
        exchange_infos = []
        for currency in self.currencies[0]["result"]:

            payload = {
                "expired": True,
                "instrument_type": "perp",
                "currency": currency["currency"],
            }

            exchange_info = await self._api_post(path_url=self.trading_currencies_request_path, data=payload)
            if "error" in exchange_info:
                if 'Instrument not found' in exchange_info['error']['message']:
                    self.logger().debug(f"Ignoring currency {currency['currency']}: not supported sport.")
                    continue
                self.logger().warning(f"Error: {exchange_info['error']['message']}")
                raise
            exchange_info["result"]["instruments"][0]["spot_price"] = currency["spot_price"]
            self._instrument_ticker.append(exchange_info["result"]["instruments"][0])
            # self._instrument_ticker[0]["spot_price"] = currency["spot_price"]

            exchange_infos.append(exchange_info["result"]["instruments"][0])
        return exchange_infos

    async def get_all_pairs_prices(self) -> Dict[str, Any]:
        res = []
        tasks = []
        if len(self._instrument_ticker) == 0:
            await self._make_trading_rules_request()
        for token in self._instrument_ticker:
            payload = {"instrument_name": token["instrument_name"]}
            tasks.append(self._api_post(path_url=CONSTANTS.TICKER_PRICE_CHANGE_PATH_URL, data=payload))
        results = await safe_gather(*tasks, return_exceptions=True)
        for result in results:
            pair_price_data = result["result"]

            data = {
                "symbol": {
                    "instrument_name": pair_price_data["instrument_name"],
                    "best_bid": pair_price_data["best_bid_price"],
                    "best_ask": pair_price_data["best_ask_price"],
                }
            }
            res.append(data)
        return res

    def _is_request_exception_related_to_time_synchronizer(self, request_exception: Exception):
        return False

    def _initialize_trading_pair_symbols_from_exchange_info(self, exchange_info: List):
        mapping = bidict()

        for _info in filter(web_utils.is_exchange_information_valid, exchange_info):
            ex_name = _info["instrument_name"]

            base, _quote = ex_name.split("-")
            _quote = "USDC"
            trading_pair = combine_to_hb_trading_pair(base, _quote)
            mapping[ex_name] = trading_pair
        self._set_trading_pair_symbol_map(mapping)

    async def _update_trading_rules(self):
        exchange_info = await self._make_trading_rules_request()
        trading_rules_list = await self._format_trading_rules(exchange_info)
        self._trading_rules.clear()
        for trading_rule in trading_rules_list:
            self._trading_rules[trading_rule.trading_pair] = trading_rule
        self._initialize_trading_pair_symbols_from_exchange_info(exchange_info=exchange_info)

    def _create_web_assistants_factory(self) -> WebAssistantsFactory:
        return web_utils.build_api_factory(
            throttler=self._throttler,
            time_synchronizer=self._time_synchronizer,
            domain=self._domain,
            auth=self._auth)

    def _create_order_book_data_source(self) -> OrderBookTrackerDataSource:
        return DerivePerpetualAPIOrderBookDataSource(
            trading_pairs=self._trading_pairs,
            connector=self,
            api_factory=self._web_assistants_factory,
            domain=self.domain,
        )

    def _create_user_stream_data_source(self) -> UserStreamTrackerDataSource:
        return DerivePerpetualAPIUserStreamDataSource(
            auth=self._auth,
            trading_pairs=self._trading_pairs,
            connector=self,
            api_factory=self._web_assistants_factory,
            domain=self.domain,
        )

    def _is_order_not_found_during_status_update_error(self, status_update_exception: Exception) -> bool:
        return CONSTANTS.ORDER_NOT_EXIST_MESSAGE in str(status_update_exception)

    def _is_order_not_found_during_cancelation_error(self, cancelation_exception: Exception) -> bool:
        return CONSTANTS.UNKNOWN_ORDER_MESSAGE in str(cancelation_exception)

    def quantize_order_price(self, trading_pair: str, price: Decimal) -> Decimal:
        """
        Applies trading rule to quantize order price.
        """
        d_price = Decimal(round(float(f"{price:.5g}"), 6))
        return d_price

    def _get_fee(self,
                 base_currency: str,
                 quote_currency: str,
                 order_type: OrderType,
                 order_side: TradeType,
                 amount: Decimal,
                 price: Decimal = s_decimal_NaN,
                 is_maker: Optional[bool] = None) -> TradeFeeBase:
        is_maker = order_type is OrderType.LIMIT_MAKER
        trade_base_fee = build_trade_fee(
            exchange=self.name,
            is_maker=is_maker,
            order_side=order_side,
            order_type=order_type,
            amount=amount,
            price=price,
            base_currency=base_currency.upper(),
            quote_currency=quote_currency.upper()
        )
        return trade_base_fee

    async def _status_polling_loop_fetch_updates(self):
        await safe_gather(
            self._update_trade_history(),
            self._update_order_status(),
            self._update_balances(),
            self._update_positions(),
        )

    async def _update_order_status(self):
        await self._update_orders()

    async def _update_lost_orders_status(self):
        await self._update_lost_orders()

    async def _update_trading_fees(self):
        """
        Update fees information from the derivative exchange.
        """
        pass

    async def _place_cancel(self, order_id: str, tracked_order: InFlightOrder):
        oid = await tracked_order.get_exchange_order_id()
        symbol = await self.exchange_symbol_associated_to_pair(trading_pair=tracked_order.trading_pair)
        api_params = {
            "instrument_name": symbol,
            "order_id": oid,
            "subaccount_id": self._sub_id
        }
        cancel_result = await self._api_post(
            path_url=CONSTANTS.CANCEL_ORDER_URL,
            data=api_params,
            is_auth_required=True)

        if "error" in cancel_result:
            if 'Does not exist' in cancel_result['error']['message']:
                self.logger().debug(f"The order {order_id} does not exist on DerivePerpetual s. "
                                    f"No cancelation needed.")
                await self._order_tracker.process_order_not_found(order_id)
            raise IOError(f'{cancel_result["error"]["message"]}')
        else:
            if cancel_result["result"]["order_status"] == "cancelled":
                return True
        return False

    # === Orders placing ===

    def buy(self,
            trading_pair: str,
            amount: Decimal,
            order_type=OrderType.LIMIT,
            price: Decimal = s_decimal_NaN,
            **kwargs) -> str:
        """
        Creates a promise to create a buy order using the parameters

        :param trading_pair: the token pair to operate with
        :param amount: the order amount
        :param order_type: the type of order to create (MARKET, LIMIT, LIMIT_MAKER)
        :param price: the order price

        :return: the id assigned by the connector to the order (the client id)
        """
        order_id = get_new_client_order_id(
            is_buy=True,
            trading_pair=trading_pair,
            hbot_order_id_prefix=self.client_order_id_prefix,
            max_id_len=self.client_order_id_max_length
        )
        md5 = hashlib.md5()
        md5.update(order_id.encode('utf-8'))
        hex_order_id = f"0x{md5.hexdigest()}"
        price = self.quantize_order_price(trading_pair, price)

        safe_ensure_future(self._create_order(
            trade_type=TradeType.BUY,
            order_id=hex_order_id,
            trading_pair=trading_pair,
            amount=amount,
            order_type=order_type,
            price=price,
            **kwargs))
        return hex_order_id

    def sell(self,
             trading_pair: str,
             amount: Decimal,
             order_type: OrderType = OrderType.LIMIT,
             price: Decimal = s_decimal_NaN,
             **kwargs) -> str:
        """
        Creates a promise to create a sell order using the parameters.
        :param trading_pair: the token pair to operate with
        :param amount: the order amount
        :param order_type: the type of order to create (MARKET, LIMIT, LIMIT_MAKER)
        :param price: the order price
        :return: the id assigned by the connector to the order (the client id)
        """
        order_id = get_new_client_order_id(
            is_buy=False,
            trading_pair=trading_pair,
            hbot_order_id_prefix=self.client_order_id_prefix,
            max_id_len=self.client_order_id_max_length
        )
        md5 = hashlib.md5()
        md5.update(order_id.encode('utf-8'))
        hex_order_id = f"0x{md5.hexdigest()}"
        price = self.quantize_order_price(trading_pair, price)

        safe_ensure_future(self._create_order(
            trade_type=TradeType.SELL,
            order_id=hex_order_id,
            trading_pair=trading_pair,
            amount=amount,
            order_type=order_type,
            price=price,
            **kwargs))
        return hex_order_id

    async def _place_order(
            self,
            order_id: str,
            trading_pair: str,
            amount: Decimal,
            trade_type: TradeType,
            order_type: OrderType,
            price: Decimal,
            position_action: PositionAction = PositionAction.NIL,
            **kwargs,
    ) -> Tuple[str, float]:
        """
        Creates an order on the derivative exchange using the specified parameters.
        """
        symbol = await self.exchange_symbol_associated_to_pair(trading_pair=trading_pair)
        if len(self._instrument_ticker) > 0:
            instrument = [next((pair for pair in self._instrument_ticker if symbol == pair["instrument_name"]), None)]
        param_order_type = "gtc"
        if order_type is OrderType.LIMIT_MAKER:
            param_order_type = "gtc"
        if order_type is OrderType.MARKET:
            param_order_type = "ioc"
        type_str = DerivePerpetualDerivative.derive_perpetual_order_type(order_type)

        price_type = "limit" if type_str == "limit_maker" or type_str == "limit" else "market"
        new_price = float(f"{price:.5g}")
        api_params = {
            "asset_address": instrument[0]["base_asset_address"],
            "sub_id": instrument[0]["base_asset_sub_id"],
            "limit_price": str(new_price),
            "type": "order",
            "max_fee": str(1000),
            "amount": str(amount),
            "instrument_name": symbol,
            "label": order_id,
            "is_bid": True if trade_type is TradeType.BUY else False,
            "direction": "buy" if trade_type is TradeType.BUY else "sell",
            "order_type": price_type,
            "mmp": False,
            "time_in_force": param_order_type,
            "recipient_id": self._sub_id,
        }

        order_result = await self._api_post(
            path_url = CONSTANTS.CREATE_ORDER_URL,
            data=api_params,
            is_auth_required=True)

        if "error" in order_result:
            if "Self-crossing disallowed" in order_result["error"]["message"]:
                self.logger().warning(f"Error submitting order: {order_result['error']['message']}")
            else:
                raise IOError(f"Error submitting order {order_id}: {order_result['error']['message']}")
        else:
            o_order_result = order_result['result']
            o_data = o_order_result.get("order")
            o_id = str(o_data["order_id"])
            timestamp = o_data["creation_timestamp"] * 1e-3
            return (o_id, timestamp)

    async def _update_trade_history(self):
        orders = list(self._order_tracker.all_fillable_orders.values())
        all_fillable_orders = self._order_tracker.all_fillable_orders_by_exchange_order_id
        all_fills_response = []
        if len(orders) > 0:
            try:
                all_fills_response = await self._api_get(
                    path_url=CONSTANTS.MY_TRADES_PATH_URL,
                    params={
                        "subaccount_id": self._sub_id
                    },
                    is_auth_required=True,
                    limit_id=CONSTANTS.MY_TRADES_PATH_URL)
            except asyncio.CancelledError:
                raise
            except Exception as request_error:
                self.logger().warning(
                    f"Failed to fetch trade updates. Error: {request_error}",
                    exc_info = request_error,
                )
            for trade_fill in all_fills_response["result"]["trades"]:
                self._process_trade_rs_event_message(order_fill=trade_fill, all_fillable_order=all_fillable_orders)

    def _process_trade_rs_event_message(self, order_fill: Dict[str, Any], all_fillable_order):
        exchange_order_id = str(order_fill.get("order_id"))
        fillable_order = all_fillable_order.get(exchange_order_id)
        if fillable_order is not None:
            token = order_fill["instrument_name"].split("-")[0]
            fee_asset = token

            fee = TradeFeeBase.new_spot_fee(
                fee_schema=self.trade_fee_schema(),
                trade_type=fillable_order.trade_type,
                percent_token=fee_asset,
                flat_fees=[TokenAmount(amount=Decimal(order_fill["trade_fee"]), token=fee_asset)]
            )

            trade_update = TradeUpdate(
                trade_id=str(order_fill["trade_id"]),
                client_order_id=fillable_order.client_order_id,
                exchange_order_id=str(order_fill["order_id"]),
                trading_pair=fillable_order.trading_pair,
                fee=fee,
                fill_base_amount=Decimal(order_fill["trade_amount"]),
                fill_quote_amount=Decimal(order_fill["trade_price"]) * Decimal(order_fill["trade_amount"]),
                fill_price=Decimal(order_fill["trade_price"]),
                fill_timestamp=order_fill["timestamp"] * 1e-3,
            )

            self._order_tracker.process_trade_update(trade_update)

    async def _iter_user_event_queue(self) -> AsyncIterable[Dict[str, any]]:
        while True:
            try:
                yield await self._user_stream_tracker.user_stream.get()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().network(
                    "Unknown error. Retrying after 1 seconds.",
                    exc_info=True,
                    app_warning_msg="Could not fetch user events from DerivePerpetual. Check API key and network connection.",
                )
                await self._sleep(1.0)

    async def _user_stream_event_listener(self):
        """
        Listens to messages from _user_stream_tracker.user_stream queue.
        Traders, Orders, and Balance updates from the WS.
        """
        user_channels = [
            f"{self._sub_id}.{CONSTANTS.USER_ORDERS_ENDPOINT_NAME}",
            f"{self._sub_id}.{CONSTANTS.USEREVENT_ENDPOINT_NAME}",
        ]
        async for event_message in self._iter_user_event_queue():
            try:
                if isinstance(event_message, dict):
                    channel: str = event_message.get("channel", None)
                    results = event_message.get("data", None)
                elif event_message is asyncio.CancelledError:
                    raise asyncio.CancelledError
                else:
                    raise Exception(event_message)
                if channel not in user_channels:
                    self.logger().error(
                        f"Unexpected message in user stream: {event_message}.", exc_info=True)
                    continue
                if channel == user_channels[0] and results is not None:
                    for order_msg in results:
                        self._process_order_message(order_msg)
                elif channel == user_channels[1] and results is not None:
                    for trade_msg in results:
                        await self._process_trade_message(trade_msg)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().error(
                    "Unexpected error in user stream listener loop.", exc_info=True)
                await self._sleep(5.0)

    async def _process_trade_message(self, trade: Dict[str, Any], client_order_id: Optional[str] = None):
        """
        Updates in-flight order and trigger order filled event for trade message received. Triggers order completed
        event if the total executed amount equals to the specified order amount.
        Example Trade:
        """
        exchange_order_id = str(trade.get("order_id", ""))
        tracked_order = self._order_tracker.all_fillable_orders_by_exchange_order_id.get(exchange_order_id)

        if tracked_order is None:
            all_orders = self._order_tracker.all_fillable_orders
            for k, v in all_orders.items():
                await v.get_exchange_order_id()
            _cli_tracked_orders = [o for o in all_orders.values() if exchange_order_id == o.exchange_order_id]
            if not _cli_tracked_orders:
                self.logger().debug(f"Ignoring trade message with id {client_order_id}: not in in_flight_orders.")
                return
            tracked_order = _cli_tracked_orders[0]
        trading_pair = tracked_order.trading_pair
        if trade["instrument_name"] == trading_pair:
            fee_asset = trading_pair.split("-")[1]
            fee = TradeFeeBase.new_spot_fee(
                fee_schema=self.trade_fee_schema(),
                trade_type=tracked_order.trade_type,
                percent_token=fee_asset,
                flat_fees=[TokenAmount(amount=Decimal(trade["trade_fee"]), token=fee_asset)]
            )
            trade_update: TradeUpdate = TradeUpdate(
                trade_id=str(trade["trade_id"]),
                client_order_id=tracked_order.client_order_id,
                exchange_order_id=str(trade["order_id"]),
                trading_pair=tracked_order.trading_pair,
                fill_timestamp=trade["timestamp"] * 1e-3,
                fill_price=Decimal(trade["trade_price"]),
                fill_base_amount=Decimal(trade["trade_amount"]),
                fill_quote_amount=Decimal(trade["trade_price"]) * Decimal(trade["trade_amount"]),
                fee=fee,
            )
            self._order_tracker.process_trade_update(trade_update)

    def _process_order_message(self, order_msg: Dict[str, Any]):
        """
        Updates in-flight order and triggers cancelation or failure event if needed.

        :param order_msg: The order response from either REST or web socket API (they are of the same format)

        Example Order:
        """
        client_order_id = str(order_msg.get("label", ""))
        tracked_order = self._order_tracker.all_updatable_orders.get(client_order_id)
        if not tracked_order:
            self.logger().debug(f"Ignoring order message with id {client_order_id}: not in in_flight_orders.")
            return
        current_state = order_msg["order_status"]
        order_update: OrderUpdate = OrderUpdate(
            trading_pair=tracked_order.trading_pair,
            update_timestamp=order_msg["last_update_timestamp"] * 1e-3,
            new_state=CONSTANTS.ORDER_STATE[current_state],
            client_order_id=order_msg["label"],
            exchange_order_id=str(order_msg["order_id"]),
        )
        self._order_tracker.process_order_update(order_update=order_update)

    async def _format_trading_rules(self, exchange_info_dict: List) -> List[TradingRule]:
        """
        Queries the necessary API endpoint and initialize the TradingRule object for each trading pair being traded.

        Parameters
        ----------
        exchange_info_dict:
            Trading rules dictionary response from the derivative

        {
            "result": {
                "instruments": [
                {
                    "instrument_type": "perp",
                    "instrument_name": "OP-USDC",
                    "scheduled_activation": 1728508925,
                    "scheduled_deactivation": 9223372036854776000,
                    "is_active": true,
                    "tick_size": "0.01",
                    "minimum_amount": "0.1",
                    "maximum_amount": "1000",
                    "amount_step": "0.01",
                    "mark_price_fee_rate_cap": "0",
                    "maker_fee_rate": "0.0015",
                    "taker_fee_rate": "0.0015",
                    "base_fee": "0.1",
                    "base_currency": "OP",
                    "quote_currency": "USD",
                    "option_details": null,
                    "perp_details": null,
                    "erc20_details": {
                    "decimals": 18,
                    "underlying_erc20_address": "0x15CEcd5190A43C7798dD2058308781D0662e678E",
                    "borrow_index": "1",
                    "supply_index": "1"
                    },
                    "base_asset_address": "0xE201fCEfD4852f96810C069f66560dc25B2C7A55",
                    "base_asset_sub_id": "0",
                    "pro_rata_fraction": "0",
                    "fifo_min_allocation": "0",
                    "pro_rata_amount_step": "1"
                }
                ],
                "pagination": {
                "num_pages": 1,
                "count": 1
                }
            },
            "id": "0f9131b4-2502-4f8e-afa4-adfce67a6509"
        }
        """

        trading_pair_rules = exchange_info_dict
        retval = []
        for rule in filter(web_utils.is_exchange_information_valid, trading_pair_rules):
            try:
                trading_pair = await self.trading_pair_associated_to_exchange_symbol(symbol=rule["instrument_name"])
                min_order_size = rule["minimum_amount"]
                step_size = rule["amount_step"]
                tick_size = rule["tick_size"]
                collateral_token = "USDC"
                retval.append(
                    TradingRule(
                        trading_pair,
                        min_order_size=Decimal(min_order_size),
                        min_price_increment=Decimal(str(tick_size)),
                        min_base_amount_increment=Decimal(step_size),
                        buy_order_collateral_token=collateral_token,
                        sell_order_collateral_token=collateral_token,
                    )
                )
            except Exception:
                self.logger().error(f"Error parsing the trading pair rule {exchange_info_dict}. Skipping.",
                                    exc_info=True)
        return retval

    async def _update_balances(self):
        """
        Calls the REST API to update total and available balances.
        """
        local_asset_names = set(self._account_balances.keys())
        remote_asset_names = set()

        account_info = await self._api_post(
            path_url=CONSTANTS.ACCOUNTS_PATH_URL,
            data={"subaccount_id": self._sub_id},
            is_auth_required=True)
        if "error" in account_info:
            self.logger().error(f"Error fetching account balances: {account_info['error']['message']}")
            raise
        else:
            balances = account_info["result"]["collaterals"]
            for balance_entry in balances:
                asset_name = balance_entry["asset_name"]
                free_balance = Decimal(balance_entry["amount"])
                total_balance = Decimal(balance_entry["amount"])
                self._account_available_balances[asset_name] = free_balance
                self._account_balances[asset_name] = total_balance
                remote_asset_names.add(asset_name)

            asset_names_to_remove = local_asset_names.difference(remote_asset_names)
            for asset_name in asset_names_to_remove:
                del self._account_available_balances[asset_name]
                del self._account_balances[asset_name]

    async def _request_order_status(self, tracked_order: InFlightOrder) -> OrderUpdate:
        oid = await tracked_order.get_exchange_order_id()
        client_order_id = tracked_order.client_order_id
        order_update = await self._api_post(
            path_url=CONSTANTS.ORDER_STATUS_PAATH_URL,
            data={
                "subaccount_id": self._sub_id,
                "order_id": oid
            },
            is_auth_required=True)
        if "error" in order_update:
            self.logger().debug(f"Error fetching order status for {client_order_id}: {order_update['error']['message']}")
        if "result" in order_update:
            current_state = order_update["result"]["order_status"]
            _order_update: OrderUpdate = OrderUpdate(
                trading_pair=tracked_order.trading_pair,
                update_timestamp=order_update["result"]["last_update_timestamp"] * 1e-3,
                new_state=CONSTANTS.ORDER_STATE[current_state],
                client_order_id=order_update["result"]["label"] or client_order_id,
                exchange_order_id=str(order_update["result"]["order_id"]),
            )
            return _order_update

    async def _all_trade_updates_for_order(self, order: InFlightOrder) -> List[TradeUpdate]:
        trade_updates = []

        if order.exchange_order_id is not None:
            exchange_order_id = int(order.exchange_order_id)
            trading_pair = await self.exchange_symbol_associated_to_pair(trading_pair=order.trading_pair)
            all_fills_response = await self._api_get(
                path_url=CONSTANTS.MY_TRADES_PATH_URL,
                params={
                    "instrument_name": trading_pair,
                    "order_id": exchange_order_id,
                    "subaccount_id": self._sub_id
                },
                is_auth_required=True,
                limit_id=CONSTANTS.MY_TRADES_PATH_URL)

            for trade in all_fills_response["result"]["trades"]:
                token = trade["instrument_name"].split("-")[1]
                exchange_order_id = str(trade["order_id"])
                fee = TradeFeeBase.new_spot_fee(
                    fee_schema=self.trade_fee_schema(),
                    trade_type=order.trade_type,
                    percent_token=token,
                    flat_fees=[TokenAmount(amount=Decimal(trade["trade_fee"]), token=token)]
                )
                trade_update = TradeUpdate(
                    trade_id=str(trade["trade_id"]),
                    client_order_id=order.client_order_id,
                    exchange_order_id=exchange_order_id,
                    trading_pair=trading_pair,
                    fee=fee,
                    fill_base_amount=Decimal(trade["trade_amount"]),
                    fill_quote_amount=Decimal(trade["trade_amount"]) * Decimal(trade["trade_price"]),
                    fill_price=Decimal(trade["trade_price"]),
                    fill_timestamp=trade["timestamp"] * 1e-3,
                )
                trade_updates.append(trade_update)

        return trade_updates

    async def _get_last_traded_price(self, trading_pair: str) -> float:
        exchange_symbol = await self.exchange_symbol_associated_to_pair(trading_pair=trading_pair)
        payload = {"instrument_name": exchange_symbol}
        response = await self._api_post(path_url=CONSTANTS.TICKER_PRICE_CHANGE_PATH_URL,
                                        data=payload)

        return response["result"]["mark_price"]

    async def _update_positions(self):
        positions = await self._api_post(path_url=CONSTANTS.POSITION_INFORMATION_URL,
                                         data={"subaccount_id": self._sub_id},
                                         is_auth_required=True,
                                         limit_id=CONSTANTS.POSITION_INFORMATION_URL)
        if "error" in positions:
            self.logger().error(f"Error fetching positions: {positions['error']['message']}")
        data: List[dict] = positions["result"]["positions"]
        for position in data:
            ex_trading_pair = position.get("instrument_name")
            hb_trading_pair = await self.trading_pair_associated_to_exchange_symbol(ex_trading_pair)

            position_side = PositionSide.LONG if Decimal(position.get("amount")) > 0 else PositionSide.SHORT
            unrealized_pnl = Decimal(position.get("unrealized_pnl"))
            entry_price = Decimal(position.get("index_price"))
            amount = Decimal(position.get("amount", 0))
            leverage = position.get("leverage", 0)
            pos_key = self._perpetual_trading.position_key(hb_trading_pair, position_side)
            if amount != 0:
                _position = Position(
                    trading_pair=hb_trading_pair,
                    position_side=position_side,
                    unrealized_pnl=unrealized_pnl,
                    entry_price=entry_price,
                    amount=amount,
                    leverage=Decimal(leverage)
                )
                self._perpetual_trading.set_leverage(ex_trading_pair, leverage)
                self._perpetual_trading.set_position(pos_key, _position)
            else:
                self._perpetual_trading.remove_position(pos_key)

    async def _get_position_mode(self) -> Optional[PositionMode]:
        # NOTE: This is default to ONEWAY as there is nothing available on current version of Vega
        return self._position_mode

    async def _trading_pair_position_mode_set(self, mode: PositionMode, trading_pair: str) -> Tuple[bool, str]:
        # NOTE: There is no setting to set leverage in derive
        msg = "ok"
        success = True
        return success, msg

    async def _set_trading_pair_leverage(self, mode: PositionMode, trading_pair: str) -> Tuple[bool, str]:
        # NOTE: There is no setting to set leverage in derive
        msg = "ok"
        success = True
        return success, msg

    async def _fetch_last_fee_payment(self, trading_pair: str) -> Tuple[int, Decimal, Decimal]:
        symbol = await self.exchange_symbol_associated_to_pair(trading_pair=trading_pair)
        funding_info_response = await self._api_post(path_url=CONSTANTS.GET_LAST_FUNDING_RATE_PATH_URL,
                                                     data={
                                                         "period": 3600,
                                                         "page": 1,
                                                         "page_size": 100,
                                                         "start_timestamp": self._last_funding_time(),
                                                         "instrument_name": symbol,
                                                         "subaccount_id": self._sub_id
                                                     },
                                                     is_auth_required=True,
                                                     limit_id=CONSTANTS.GET_LAST_FUNDING_RATE_PATH_URL
                                                     )
        sorted_payment_response = funding_info_response["result"]["events"]
        if len(sorted_payment_response) < 1:
            timestamp, funding_rate, payment = 0, Decimal("-1"), Decimal("-1")
            return timestamp, funding_rate, payment
        funding_payment = sorted_payment_response[0]
        _payment = Decimal(funding_payment["funding"])
        funding_rate = Decimal(funding_payment["pnl"])
        timestamp = funding_payment["timestamp"] * 1e-3
        if _payment != Decimal("0"):
            payment = _payment
        else:
            timestamp, funding_rate, payment = 0, Decimal("-1"), Decimal("-1")
        return timestamp, funding_rate, payment

    def _last_funding_time(self) -> int:
        return int(((time.time() // 3600) - 1) * 3600 * 1e3)
