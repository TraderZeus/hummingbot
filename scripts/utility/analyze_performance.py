#!/usr/bin/env python3
"""
Performance Analysis Script for Hummingbot Market Making Bot

This script analyzes Hummingbot log files to extract key performance metrics
for market making strategies, particularly for the Hyperliquid BTC-USDT bot.

Usage:
    python analyze_performance.py [log_file_path]

If no log file path is provided, it will attempt to find the most recent log file.
"""

import argparse
import datetime
import glob
import os
import re
import sys
from collections import defaultdict
from decimal import Decimal
from typing import Dict, List, Tuple

# Regular expressions for parsing log entries
FILL_PATTERN = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - .*? - (BUY|SELL) (\d+\.\d+) ([\w-]+) .* at (\d+\.\d+)"
ORDER_CREATED_PATTERN = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - .*? - Creating (BUY|SELL) order for (\d+\.\d+) .* at (\d+\.\d+)"
ERROR_PATTERN = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - .*? - (ERROR|WARNING)"
POSITION_PATTERN = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - .*? - Position: ([\w-]+), Side: (LONG|SHORT), Amount: ([\d\.]+), Entry Price: ([\d\.]+)"


class PerformanceAnalyzer:
    def __init__(self, log_file_path: str):
        self.log_file_path = log_file_path
        self.fills = []
        self.orders_created = []
        self.errors = []
        self.positions = []
        self.trading_pair = ""
        
    def parse_log(self) -> None:
        """Parse the log file and extract relevant information."""
        if not os.path.exists(self.log_file_path):
            print(f"Error: Log file {self.log_file_path} not found.")
            sys.exit(1)
            
        print(f"Analyzing log file: {self.log_file_path}")
        
        with open(self.log_file_path, 'r') as file:
            for line in file:
                # Extract order fills
                fill_match = re.search(FILL_PATTERN, line)
                if fill_match:
                    timestamp, side, amount, trading_pair, price = fill_match.groups()
                    self.fills.append({
                        'timestamp': timestamp,
                        'side': side,
                        'amount': Decimal(amount),
                        'trading_pair': trading_pair,
                        'price': Decimal(price)
                    })
                    if not self.trading_pair:
                        self.trading_pair = trading_pair
                
                # Extract order creations
                order_match = re.search(ORDER_CREATED_PATTERN, line)
                if order_match:
                    timestamp, side, amount, price = order_match.groups()
                    self.orders_created.append({
                        'timestamp': timestamp,
                        'side': side,
                        'amount': Decimal(amount),
                        'price': Decimal(price)
                    })
                
                # Extract errors and warnings
                error_match = re.search(ERROR_PATTERN, line)
                if error_match:
                    timestamp, level = error_match.groups()
                    self.errors.append({
                        'timestamp': timestamp,
                        'level': level,
                        'message': line.strip()
                    })
                    
                # Extract position information
                position_match = re.search(POSITION_PATTERN, line)
                if position_match:
                    timestamp, trading_pair, side, amount, entry_price = position_match.groups()
                    self.positions.append({
                        'timestamp': timestamp,
                        'trading_pair': trading_pair,
                        'side': side,
                        'amount': Decimal(amount),
                        'entry_price': Decimal(entry_price)
                    })
    
    def calculate_fill_rate(self) -> Tuple[Decimal, int, int]:
        """Calculate the order fill rate."""
        if not self.orders_created:
            return Decimal('0'), 0, 0
        
        fill_rate = Decimal(len(self.fills)) / Decimal(len(self.orders_created)) * 100
        return fill_rate, len(self.fills), len(self.orders_created)
    
    def calculate_pnl(self) -> Tuple[Decimal, Decimal, Decimal]:
        """Calculate estimated PnL from fills."""
        if not self.fills:
            return Decimal('0'), Decimal('0'), Decimal('0')
        
        base_bought = Decimal('0')
        base_sold = Decimal('0')
        quote_spent = Decimal('0')
        quote_received = Decimal('0')
        
        for fill in self.fills:
            if fill['side'] == 'BUY':
                base_bought += fill['amount']
                quote_spent += fill['amount'] * fill['price']
            else:  # SELL
                base_sold += fill['amount']
                quote_received += fill['amount'] * fill['price']
        
        # Calculate realized PnL (from completed round trips)
        min_round_trips = min(base_bought, base_sold)
        realized_pnl = quote_received - (quote_spent / base_bought * min_round_trips) if base_bought > 0 else Decimal('0')
        
        # Calculate unrealized PnL (from remaining inventory)
        net_inventory = base_bought - base_sold
        
        # Use the last known price as the current price
        current_price = self.fills[-1]['price'] if self.fills else Decimal('0')
        
        unrealized_pnl = Decimal('0')
        if net_inventory > 0:  # Long position
            avg_buy_price = quote_spent / base_bought if base_bought > 0 else Decimal('0')
            unrealized_pnl = net_inventory * (current_price - avg_buy_price)
        elif net_inventory < 0:  # Short position
            avg_sell_price = quote_received / base_sold if base_sold > 0 else Decimal('0')
            unrealized_pnl = -net_inventory * (avg_sell_price - current_price)
        
        total_pnl = realized_pnl + unrealized_pnl
        return total_pnl, realized_pnl, unrealized_pnl
    
    def analyze_inventory(self) -> Dict:
        """Analyze the current inventory state."""
        base_bought = sum(fill['amount'] for fill in self.fills if fill['side'] == 'BUY')
        base_sold = sum(fill['amount'] for fill in self.fills if fill['side'] == 'SELL')
        
        net_inventory = base_bought - base_sold
        inventory_skew_pct = Decimal('0')
        
        if base_bought + base_sold > 0:
            inventory_skew_pct = (base_bought - base_sold) / (base_bought + base_sold) * 100
        
        return {
            'base_bought': base_bought,
            'base_sold': base_sold,
            'net_inventory': net_inventory,
            'inventory_skew_pct': inventory_skew_pct
        }
    
    def analyze_errors(self) -> Dict:
        """Analyze errors and warnings."""
        error_count = sum(1 for e in self.errors if e['level'] == 'ERROR')
        warning_count = sum(1 for e in self.errors if e['level'] == 'WARNING')
        
        recent_errors = [e for e in self.errors if e['level'] == 'ERROR'][-5:] if error_count > 0 else []
        
        return {
            'error_count': error_count,
            'warning_count': warning_count,
            'recent_errors': recent_errors
        }
    
    def get_time_range(self) -> Tuple[str, str, str]:
        """Get the time range covered by the log."""
        if not self.fills and not self.orders_created:
            return "N/A", "N/A", "N/A"
        
        all_timestamps = []
        all_timestamps.extend([f['timestamp'] for f in self.fills])
        all_timestamps.extend([o['timestamp'] for o in self.orders_created])
        
        if not all_timestamps:
            return "N/A", "N/A", "N/A"
        
        start_time = min(all_timestamps)
        end_time = max(all_timestamps)
        
        # Parse timestamps to calculate duration
        start_dt = datetime.datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S,%f")
        end_dt = datetime.datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S,%f")
        duration = end_dt - start_dt
        
        hours, remainder = divmod(duration.total_seconds(), 3600)
        minutes, seconds = divmod(remainder, 60)
        duration_str = f"{int(hours)}h {int(minutes)}m {int(seconds)}s"
        
        return start_time, end_time, duration_str
    
    def get_current_position(self) -> Dict:
        """Get the most recent position information."""
        if not self.positions:
            return {}
        
        return self.positions[-1]
    
    def print_summary(self) -> None:
        """Print a summary of the performance analysis."""
        start_time, end_time, duration = self.get_time_range()
        fill_rate, fills_count, orders_count = self.calculate_fill_rate()
        total_pnl, realized_pnl, unrealized_pnl = self.calculate_pnl()
        inventory = self.analyze_inventory()
        error_analysis = self.analyze_errors()
        current_position = self.get_current_position()
        
        print("\n" + "="*80)
        print(f"PERFORMANCE SUMMARY FOR {self.trading_pair}")
        print("="*80)
        
        print(f"\nTime Range: {start_time} to {end_time} (Duration: {duration})")
        
        print("\nOrder Statistics:")
        print(f"  Total Orders Created: {orders_count}")
        print(f"  Total Orders Filled:  {fills_count}")
        print(f"  Fill Rate:            {fill_rate:.2f}%")
        
        print("\nProfitability:")
        print(f"  Total PnL:            {total_pnl:.8f}")
        print(f"  Realized PnL:         {realized_pnl:.8f}")
        print(f"  Unrealized PnL:       {unrealized_pnl:.8f}")
        
        print("\nInventory Analysis:")
        print(f"  Base Asset Bought:    {inventory['base_bought']:.8f}")
        print(f"  Base Asset Sold:      {inventory['base_sold']:.8f}")
        print(f"  Net Inventory:        {inventory['net_inventory']:.8f}")
        print(f"  Inventory Skew:       {inventory['inventory_skew_pct']:.2f}%")
        
        if current_position:
            print("\nCurrent Position:")
            print(f"  Trading Pair:         {current_position['trading_pair']}")
            print(f"  Side:                 {current_position['side']}")
            print(f"  Amount:               {current_position['amount']}")
            print(f"  Entry Price:          {current_position['entry_price']}")
        
        print("\nError Analysis:")
        print(f"  Total Errors:          {error_analysis['error_count']}")
        print(f"  Total Warnings:        {error_analysis['warning_count']}")
        
        if error_analysis['recent_errors']:
            print("\nRecent Errors:")
            for error in error_analysis['recent_errors']:
                print(f"  {error['timestamp']} - {error['message'][:100]}...")
        
        print("\nRecommendations:")
        if fill_rate < 10:
            print("  - Consider reducing your spreads to increase fill rate")
        elif fill_rate > 90:
            print("  - Consider increasing your spreads to improve profitability")
            
        if abs(inventory['inventory_skew_pct']) > 50:
            print("  - Your inventory is becoming skewed. Consider adjusting spreads to rebalance")
            
        if error_analysis['error_count'] > 10:
            print("  - Investigate the errors in your log file")
            
        print("\n" + "="*80)


def find_latest_log_file() -> str:
    """Find the most recent Hummingbot log file."""
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")
    log_files = glob.glob(os.path.join(log_dir, "*.log"))
    
    if not log_files:
        print(f"No log files found in {log_dir}")
        sys.exit(1)
    
    return max(log_files, key=os.path.getmtime)


def main():
    parser = argparse.ArgumentParser(description="Analyze Hummingbot market making performance")
    parser.add_argument("log_file", nargs="?", help="Path to the Hummingbot log file")
    args = parser.parse_args()
    
    log_file_path = args.log_file if args.log_file else find_latest_log_file()
    
    analyzer = PerformanceAnalyzer(log_file_path)
    analyzer.parse_log()
    analyzer.print_summary()


if __name__ == "__main__":
    main()