# Quick Start Guide: Hyperliquid BTC-USDT Market Making Bot

This guide provides step-by-step instructions to get your market making bot up and running quickly.

## Initial Setup

1. **Navigate to the Hummingbot directory**:
   ```bash
   cd hummingbot
   ```

2. **Make the start script executable** (if not already done):
   ```bash
   chmod +x start_hyperliquid_market_maker.sh
   ```

3. **Start the bot**:
   ```bash
   ./start_hyperliquid_market_maker.sh
   ```

4. **Begin trading**:
   Once Hummingbot starts, type `start` to begin trading.

## First 24 Hours: Monitoring Checklist

During the first day of operation, check these key indicators:

### Every 2-3 Hours

- [ ] **Order Placement**: Are orders being placed successfully?
- [ ] **Order Fills**: Are any orders being filled?
- [ ] **Error Messages**: Are there any error messages in the logs?

### After 12 Hours

- [ ] **Fill Rate**: What percentage of orders are being filled?
- [ ] **Spread Analysis**: Are the configured spreads appropriate for current market conditions?
- [ ] **Balance Changes**: How is your balance changing over time?

### After 24 Hours

- [ ] **PnL Assessment**: Are you profitable after accounting for fees?
- [ ] **Inventory Balance**: Is your inventory becoming skewed toward base or quote asset?
- [ ] **Parameter Review**: Do any parameters need adjustment based on performance?

## First Adjustments

Based on your 24-hour observations, consider these common first adjustments:

### If Orders Aren't Being Filled

1. **Reduce Spreads**:
   ```
   # In conf/strategies/hyperliquid_btc_market_maker.yml
   bid_spread: 0.002   # Reduced from 0.003
   ask_spread: 0.002   # Reduced from 0.003
   ```

2. **Increase Order Size** (if market depth supports it):
   ```
   # In conf/strategies/hyperliquid_btc_market_maker.yml
   order_amount: 0.002  # Increased from 0.001
   ```

### If Orders Are Filling Too Quickly

1. **Increase Spreads**:
   ```
   # In conf/strategies/hyperliquid_btc_market_maker.yml
   bid_spread: 0.004   # Increased from 0.003
   ask_spread: 0.004   # Increased from 0.003
   ```

2. **Decrease Order Refresh Time**:
   ```
   # In conf/strategies/hyperliquid_btc_market_maker.yml
   order_refresh_time: 15  # Decreased from 20
   ```

## Common Commands

While the bot is running, you can use these commands:

- `status`: View the current status of the bot
- `history`: View the trading history
- `balance`: Check your account balance
- `positions`: View your current positions (for perpetual futures)
- `config spread`: Change the bid/ask spread
- `config leverage`: Change the leverage setting
- `stop`: Stop the bot
- `exit`: Exit Hummingbot

## Troubleshooting

### Connection Issues

If you experience connection issues:
1. Check your internet connection
2. Verify that Hyperliquid API is accessible
3. Confirm your API keys are correct

### Order Placement Failures

If orders fail to be placed:
1. Check for sufficient balance
2. Verify minimum order size requirements
3. Ensure your leverage settings are valid

### Performance Issues

If the bot is running slowly:
1. Increase the order refresh time
2. Check system resources (CPU, memory)
3. Ensure no other resource-intensive processes are running

## Next Steps

After your initial testing period:

1. Review the detailed `PERFORMANCE_TUNING_GUIDE.md` for advanced optimization
2. Gradually increase your order sizes as you gain confidence
3. Experiment with different parameter combinations to find optimal settings
4. Consider implementing a more sophisticated inventory management approach

Remember: Start small, monitor closely, and adjust parameters gradually based on observed performance.