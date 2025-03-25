import logging
import os
from decimal import Decimal
from typing import Dict, List

from pydantic import Field

from hummingbot.client.config.config_data_types import BaseClientModel, ClientFieldData
from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.data_type.common import OrderType, PriceType, TradeType
from hummingbot.core.data_type.order_candidate import OrderCandidate
from hummingbot.core.event.events import OrderFilledEvent
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase


class HyperliquidMarketMakerConfig(BaseClientModel):
    script_file_name: str = Field(default_factory=lambda: os.path.basename(__file__))
    
    # Exchange and trading pair settings
    exchange: str = Field("hyperliquid_perpetual", client_data=ClientFieldData(
        prompt_on_new=True, prompt=lambda mi: "Exchange where the bot will trade"))
    trading_pair: str = Field("BTC-USDT", client_data=ClientFieldData(
        prompt_on_new=True, prompt=lambda mi: "Trading pair in which the bot will place orders"))
    
    # Order settings
    order_amount: Decimal = Field(0.01, client_data=ClientFieldData(
        prompt_on_new=True, prompt=lambda mi: "Order amount (denominated in base asset)"))
    bid_spread: Decimal = Field(0.001, client_data=ClientFieldData(
        prompt_on_new=True, prompt=lambda mi: "Bid order spread (in percent)"))
    ask_spread: Decimal = Field(0.001, client_data=ClientFieldData(
        prompt_on_new=True, prompt=lambda mi: "Ask order spread (in percent)"))
    
    # Strategy settings
    order_refresh_time: int = Field(15, client_data=ClientFieldData(
        prompt_on_new=True, prompt=lambda mi: "Order refresh time (in seconds)"))
    price_type: str = Field("mid", client_data=ClientFieldData(
        prompt_on_new=True, prompt=lambda mi: "Price type to use (mid or last)"))
    
    # Risk management
    max_order_age: int = Field(1800, client_data=ClientFieldData(
        prompt_on_new=True, prompt=lambda mi: "Maximum order age in seconds before cancellation"))
    
    # Position management
    leverage: int = Field(1, client_data=ClientFieldData(
        prompt_on_new=True, prompt=lambda mi: "Leverage to use for trading (1-100)"))
    
    # Wallet settings
    wallet_address: str = Field("0xf1c38123438cC1e46ED31048d84761cF206f79e5", client_data=ClientFieldData(
        prompt_on_new=True, prompt=lambda mi: "API wallet address"))
    use_vault: bool = Field(True, client_data=ClientFieldData(
        prompt_on_new=True, prompt=lambda mi: "Use vault for trading (True/False)"))


class HyperliquidMarketMaker(ScriptStrategyBase):
    """
    Market Making Bot for Hyperliquid Exchange
    
    Description:
    This bot places buy and sell orders around the reference price (mid price or last traded price)
    for BTC-USDT on Hyperliquid, with distances defined by the bid_spread and ask_spread.
    Every order_refresh_time in seconds, the bot cancels and replaces the orders.
    
    The bot includes risk management features like maximum order age and leverage settings.
    """

    create_timestamp = 0
    price_source = PriceType.MidPrice
    
    @classmethod
    def init_markets(cls, config: HyperliquidMarketMakerConfig):
        cls.markets = {config.exchange: {config.trading_pair}}
        cls.price_source = PriceType.LastTrade if config.price_type == "last" else PriceType.MidPrice

    def __init__(self, connectors: Dict[str, ConnectorBase], config: HyperliquidMarketMakerConfig):
        super().__init__(connectors)
        self.config = config
        self.set_leverage()
        
    def set_leverage(self):
        """Set the leverage for the trading pair"""
        try:
            self.logger().info(f"Setting leverage to {self.config.leverage}x for {self.config.trading_pair}")
            self.connectors[self.config.exchange].set_leverage(
                trading_pair=self.config.trading_pair,
                leverage=self.config.leverage
            )
        except Exception as e:
            self.logger().error(f"Error setting leverage: {str(e)}")

    def on_tick(self):
        """Main logic executed on each tick"""
        if self.create_timestamp <= self.current_timestamp:
            # Cancel existing orders
            self.cancel_all_orders()
            
            # Create and place new orders
            proposal: List[OrderCandidate] = self.create_proposal()
            proposal_adjusted: List[OrderCandidate] = self.adjust_proposal_to_budget(proposal)
            self.place_orders(proposal_adjusted)
            
            # Set the next order refresh time
            self.create_timestamp = self.config.order_refresh_time + self.current_timestamp

    def create_proposal(self) -> List[OrderCandidate]:
        """Create buy and sell order proposals based on the current market price and configured spreads"""
        # Get the reference price based on the configured price type
        ref_price = self.connectors[self.config.exchange].get_price_by_type(
            self.config.trading_pair, 
            self.price_source
        )
        
        # Calculate buy and sell prices using the configured spreads
        buy_price = ref_price * Decimal(1 - self.config.bid_spread)
        sell_price = ref_price * Decimal(1 + self.config.ask_spread)
        
        # Log the prices for debugging
        self.logger().info(f"Reference price: {ref_price}, Buy price: {buy_price}, Sell price: {sell_price}")

        # Create buy order
        buy_order = OrderCandidate(
            trading_pair=self.config.trading_pair,
            is_maker=True,
            order_type=OrderType.LIMIT,
            order_side=TradeType.BUY,
            amount=Decimal(self.config.order_amount),
            price=buy_price
        )

        # Create sell order
        sell_order = OrderCandidate(
            trading_pair=self.config.trading_pair,
            is_maker=True,
            order_type=OrderType.LIMIT,
            order_side=TradeType.SELL,
            amount=Decimal(self.config.order_amount),
            price=sell_price
        )

        return [buy_order, sell_order]

    def adjust_proposal_to_budget(self, proposal: List[OrderCandidate]) -> List[OrderCandidate]:
        """Adjust the order proposal based on available budget"""
        proposal_adjusted = self.connectors[self.config.exchange].budget_checker.adjust_candidates(
            proposal, 
            all_or_none=True
        )
        return proposal_adjusted

    def place_orders(self, proposal: List[OrderCandidate]) -> None:
        """Place the orders from the proposal"""
        for order in proposal:
            self.place_order(connector_name=self.config.exchange, order=order)

    def place_order(self, connector_name: str, order: OrderCandidate):
        """Place a single order"""
        if order.order_side == TradeType.SELL:
            self.sell(
                connector_name=connector_name,
                trading_pair=order.trading_pair,
                amount=order.amount,
                order_type=order.order_type,
                price=order.price
            )
        elif order.order_side == TradeType.BUY:
            self.buy(
                connector_name=connector_name,
                trading_pair=order.trading_pair,
                amount=order.amount,
                order_type=order.order_type,
                price=order.price
            )

    def cancel_all_orders(self):
        """Cancel all active orders"""
        for order in self.get_active_orders(connector_name=self.config.exchange):
            # Check if the order is too old
            order_age = int(self.current_timestamp - order.creation_timestamp)
            if order_age > self.config.max_order_age:
                self.logger().info(f"Cancelling order {order.client_order_id} because it's too old ({order_age} seconds)")
            
            self.cancel(self.config.exchange, order.trading_pair, order.client_order_id)

    def did_fill_order(self, event: OrderFilledEvent):
        """Callback when an order is filled"""
        msg = (f"{event.trade_type.name} {round(event.amount, 4)} {event.trading_pair} "
               f"{self.config.exchange} at {round(event.price, 2)}")
        self.logger().info(msg)
        self.notify_hb_app_with_timestamp(msg)
        
        # Log position information after a fill
        self.log_position_information()
        
    def log_position_information(self):
        """Log current position information"""
        try:
            positions = self.connectors[self.config.exchange].get_positions()
            for position in positions:
                if position.trading_pair == self.config.trading_pair:
                    self.logger().info(
                        f"Position: {position.trading_pair}, "
                        f"Side: {'LONG' if position.amount > 0 else 'SHORT'}, "
                        f"Amount: {position.amount}, "
                        f"Entry Price: {position.entry_price}, "
                        f"Leverage: {position.leverage}"
                    )
        except Exception as e:
            self.logger().error(f"Error fetching position information: {str(e)}")