# Hyperliquid BTC-USDT Market Making Bot

This README provides instructions on how to set up and run the Hyperliquid BTC-USDT market making bot using Hummingbot.

## Overview

This bot implements a simple market making strategy for the BTC-USDT trading pair on Hyperliquid. It places buy and sell orders around the mid-price with configurable spreads, and refreshes these orders at regular intervals.

## Prerequisites

- Hummingbot installed and configured
- Hyperliquid account with API keys
- Sufficient funds in your Hyperliquid account

## Configuration Files

The following configuration files have been created:

1. **Strategy Script**: `scripts/hyperliquid_btc_market_maker.py`
2. **Strategy Config**: `conf/strategies/hyperliquid_btc_market_maker.yml`
3. **API Keys Config**: `conf/connectors/hyperliquid_perpetual_api_keys.json`

## Setup Instructions

### 1. Install Hummingbot

If you haven't already installed Hummingbot, run the installation script:

```bash
cd hummingbot
./install
```

### 2. Verify API Keys

Ensure your API keys are correctly configured in `conf/connectors/hyperliquid_perpetual_api_keys.json`:

```json
{
    "hyperliquid_perpetual_api_key": "YOUR_WALLET_ADDRESS",
    "hyperliquid_perpetual_secret_key": "YOUR_PRIVATE_KEY",
    "hyperliquid_perpetual_use_vault": true
}
```

### 3. Adjust Strategy Parameters

Review and adjust the strategy parameters in `conf/strategies/hyperliquid_btc_market_maker.yml` as needed:

- `order_amount`: Size of each order in BTC
- `bid_spread` and `ask_spread`: Distance from mid-price for buy and sell orders
- `order_refresh_time`: How often to cancel and replace orders
- `leverage`: Trading leverage (1-100)

## Running the Bot

### 1. Start Hummingbot

```bash
cd hummingbot
./start
```

### 2. Import the Strategy

Once Hummingbot is running, import the strategy:

```
>>> import_strategy hyperliquid_btc_market_maker.yml
```

### 3. Start the Strategy

```
>>> start
```

### 4. Monitor the Bot

The bot will log its activities in the Hummingbot console. You can use the following commands to monitor its performance:

- `status`: View the current status of the bot
- `history`: View the trading history
- `balance`: Check your account balance
- `positions`: View your current positions (for perpetual futures)

### 5. Stop the Bot

To stop the bot, use the command:

```
>>> stop
```

## Risk Warning

Trading cryptocurrencies involves significant risk. This bot is provided as-is with no guarantees. Always start with small amounts and monitor the bot's performance closely.

## Customization

You can modify the strategy script (`scripts/hyperliquid_btc_market_maker.py`) to add additional features or adjust the trading logic according to your needs.

## Troubleshooting

If you encounter issues:

1. Check the Hummingbot logs for error messages
2. Verify your API keys are correct
3. Ensure you have sufficient funds in your account
4. Check that the trading pair is available on Hyperliquid

For more detailed information, refer to the [Hummingbot documentation](https://docs.hummingbot.org/).