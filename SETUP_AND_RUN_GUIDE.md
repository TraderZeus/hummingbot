# Setting Up and Running Your Hyperliquid Market Making Bot

This guide provides detailed instructions for setting up and running your Hyperliquid BTC-USDT market making bot in a proper environment.

## Prerequisites

Before you can run the bot, you need to have the following installed:

1. **Anaconda or Miniconda**: Required for the Python environment
   - Download from: https://docs.conda.io/en/latest/miniconda.html

2. **Git**: For cloning the repository
   - Download from: https://git-scm.com/downloads

## Setup Instructions

### 1. Clone Your Fork

```bash
git clone https://github.com/TraderZeus/hummingbot.git
cd hummingbot
```

### 2. Install Hummingbot

Run the installation script:

```bash
./install
```

This will:
- Create a conda environment called "hummingbot"
- Install all required dependencies
- Set up the Hummingbot application

### 3. Verify Configuration Files

Ensure these configuration files exist and contain the correct information:

1. **Strategy Configuration**:
   ```
   conf/strategies/hyperliquid_btc_market_maker.yml
   ```

2. **API Keys Configuration**:
   ```
   conf/connectors/hyperliquid_perpetual_api_keys.json
   ```

If they don't exist, create them with the following content:

**hyperliquid_btc_market_maker.yml**:
```yaml
# Hyperliquid BTC-USDT Market Making Strategy Configuration
# Adjusted for initial testing with conservative parameters

# Script filename
script_file_name: hyperliquid_btc_market_maker.py

# Exchange and trading pair settings
exchange: hyperliquid_perpetual
trading_pair: BTC-USDT

# Order settings
# Start with a very small amount for testing, then gradually increase
order_amount: 0.001  # Small amount in BTC for initial testing

# Spread settings
# Wider spreads are more conservative but may result in fewer fills
bid_spread: 0.003   # 0.3%
ask_spread: 0.003   # 0.3%

# Strategy settings
# Shorter refresh times make the bot more responsive but increase API calls
order_refresh_time: 20  # Refresh orders every 20 seconds
price_type: mid

# Risk management
max_order_age: 900     # Cancel orders older than 15 minutes

# Position management
leverage: 1             # Use 1x leverage for conservative trading

# Wallet settings
wallet_address: "0xf1c38123438cC1e46ED31048d84761cF206f79e5"
use_vault: true
```

**hyperliquid_perpetual_api_keys.json**:
```json
{
    "hyperliquid_perpetual_api_key": "0xf1c38123438cC1e46ED31048d84761cF206f79e5",
    "hyperliquid_perpetual_secret_key": "0x4bfa3c1f21e901379a9dc4e0f1d5f8633ec43417fb42038ac3ad3e50c8b483fd",
    "hyperliquid_perpetual_use_vault": true
}
```

## Running the Bot

### 1. Activate the Hummingbot Environment

```bash
conda activate hummingbot
```

### 2. Start the Bot

You can use our custom start script:

```bash
./start_hyperliquid_market_maker.sh
```

Or start Hummingbot directly and import the strategy:

```bash
./start
```

Then, once Hummingbot is running:

```
>>> import_strategy conf/strategies/hyperliquid_btc_market_maker.yml
>>> start
```

### 3. Monitor the Bot

While the bot is running, you can use these commands:

- `status`: View the current status of the bot
- `history`: View the trading history
- `balance`: Check your account balance
- `positions`: View your current positions

### 4. Analyze Performance

After running the bot for some time, analyze its performance:

```bash
./scripts/utility/analyze_performance.py
```

## Troubleshooting

### Common Issues

1. **Conda Environment Not Found**:
   ```
   Error: 'hummingbot' conda environment is not activated.
   ```
   Solution: Make sure you've run `conda activate hummingbot` before starting the bot.

2. **API Key Issues**:
   ```
   Error connecting to exchange
   ```
   Solution: Verify your API keys in `conf/connectors/hyperliquid_perpetual_api_keys.json`.

3. **Order Placement Failures**:
   Solution: Check your balance and ensure minimum order size requirements are met.

### Getting Help

If you encounter issues not covered here:

1. Check the Hummingbot documentation: https://docs.hummingbot.org/
2. Join the Hummingbot Discord: https://discord.gg/hummingbot
3. Review the logs in the `logs/` directory for detailed error messages

## Next Steps

After your initial testing period:

1. Review the detailed `PERFORMANCE_TUNING_GUIDE.md` for advanced optimization
2. Gradually increase your order sizes as you gain confidence
3. Experiment with different parameter combinations to find optimal settings

Remember: Start small, monitor closely, and adjust parameters gradually based on observed performance.