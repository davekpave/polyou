#!/usr/bin/env python3
"""Backtest proposed strategy changes on historical data."""

import csv
from pathlib import Path
import statistics

EXITS_CSV = Path("logs/shadow_exits.csv")

def win_logic(side, exit_type, profit):
    """Determine if a trade was a win."""
    if exit_type == 'EXPIRY_BID':
        return True
    elif exit_type == 'SETTLED_ZERO':
        return False
    else:
        return float(profit) > 0

def backtest_strategy(stop_loss=None, only_up=False, skip_down=False):
    """Backtest a strategy with given parameters."""
    with open(EXITS_CSV, newline='') as f:
        reader = csv.DictReader(f)
        
        trades = []
        for row in reader:
            if row['symbol'] != 'BTCUSD':
                continue
            
            side = row['side']
            
            # Apply side filter
            if only_up and side != 'UP':
                continue
            if skip_down and side == 'DOWN':
                continue
            
            entry_price = float(row['entry_price'])
            exit_price = float(row['exit_price'])
            profit = float(row['profit_per_share'])
            exit_type = row['exit_type']
            
            # Apply stop-loss
            if stop_loss is not None and profit < stop_loss:
                # Simulate exiting at stop-loss
                profit = stop_loss
                is_win = False
            else:
                is_win = win_logic(side, exit_type, profit)
            
            trades.append({
                'side': side,
                'profit': profit,
                'is_win': is_win,
                'original_profit': float(row['profit_per_share']),
            })
        
        return trades

def print_strategy_results(name, trades):
    """Print results for a strategy."""
    if not trades:
        print(f"{name}: No trades")
        return
    
    wins = [t for t in trades if t['is_win']]
    losses = [t for t in trades if not t['is_win']]
    
    total_pnl = sum(t['profit'] for t in trades)
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    
    avg_win = statistics.mean([t['profit'] for t in wins]) if wins else 0
    avg_loss = statistics.mean([t['profit'] for t in losses]) if losses else 0
    
    print(f"\n{name}")
    print("=" * 60)
    print(f"Total trades:   {len(trades)}")
    print(f"Wins:           {len(wins)} ({win_rate:.1f}%)")
    print(f"Losses:         {len(losses)}")
    print(f"Total P&L:      {total_pnl:+.4f}")
    print(f"Avg win:        {avg_win:+.4f}")
    print(f"Avg loss:       {avg_loss:+.4f}")
    if avg_loss < 0:
        print(f"Risk/Reward:    {avg_win/abs(avg_loss):.2f}:1")
    print(f"Expected value: {total_pnl/len(trades):+.4f} per trade")

def compare_strategies():
    """Compare different strategy variations."""
    print("STRATEGY BACKTEST COMPARISON")
    print("=" * 60)
    
    # Current strategy (baseline)
    baseline = backtest_strategy()
    print_strategy_results("1. BASELINE (Current - All Trades)", baseline)
    
    # Only UP trades
    only_up = backtest_strategy(only_up=True)
    print_strategy_results("2. UP TRADES ONLY", only_up)
    
    # Stop-loss at -0.25
    stop_25 = backtest_strategy(stop_loss=-0.25)
    print_strategy_results("3. ALL TRADES + Stop-Loss @ -0.25", stop_25)
    
    # Stop-loss at -0.30
    stop_30 = backtest_strategy(stop_loss=-0.30)
    print_strategy_results("4. ALL TRADES + Stop-Loss @ -0.30", stop_30)
    
    # UP only + stop-loss at -0.25
    up_stop_25 = backtest_strategy(only_up=True, stop_loss=-0.25)
    print_strategy_results("5. UP ONLY + Stop-Loss @ -0.25", up_stop_25)
    
    # UP only + stop-loss at -0.30
    up_stop_30 = backtest_strategy(only_up=True, stop_loss=-0.30)
    print_strategy_results("6. UP ONLY + Stop-Loss @ -0.30", up_stop_30)
    
    # Skip DOWN trades (same as UP only for BTC)
    skip_down = backtest_strategy(skip_down=True)
    print_strategy_results("7. SKIP DOWN (Keep UP)", skip_down)
    
    # Skip DOWN + stop-loss
    skip_down_stop = backtest_strategy(skip_down=True, stop_loss=-0.30)
    print_strategy_results("8. SKIP DOWN + Stop-Loss @ -0.30", skip_down_stop)
    
    print("\n" + "=" * 60)
    print("RECOMMENDATION")
    print("=" * 60)
    
    # Compare best strategies
    strategies = [
        ("Baseline", sum(t['profit'] for t in baseline)),
        ("UP Only", sum(t['profit'] for t in only_up)),
        ("UP + SL@-0.30", sum(t['profit'] for t in up_stop_30)),
    ]
    
    best_name, best_pnl = max(strategies, key=lambda x: x[1])
    print(f"Best strategy: {best_name} with {best_pnl:+.4f} total P&L")
    
    # Calculate improvement
    baseline_pnl = strategies[0][1]
    improvement = best_pnl - baseline_pnl
    improvement_pct = (improvement / abs(baseline_pnl) * 100) if baseline_pnl != 0 else 0
    print(f"Improvement over baseline: {improvement:+.4f} ({improvement_pct:+.1f}%)")

if __name__ == "__main__":
    compare_strategies()
