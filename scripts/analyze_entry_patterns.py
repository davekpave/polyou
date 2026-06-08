#!/usr/bin/env python3
"""Analyze entry patterns to find what predicts success."""

import csv
from pathlib import Path
from collections import defaultdict
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

def analyze_entry_prices():
    """Analyze entry price patterns for BTCUSD UP trades."""
    with open(EXITS_CSV, newline='') as f:
        reader = csv.DictReader(f)
        
        # Filter for BTCUSD UP trades only
        btc_up_trades = []
        for row in reader:
            if row['symbol'] == 'BTCUSD' and row['side'] == 'UP':
                is_win = win_logic(row['side'], row['exit_type'], row['profit_per_share'])
                btc_up_trades.append({
                    'entry_price': float(row['entry_price']),
                    'exit_price': float(row['exit_price']),
                    'profit': float(row['profit_per_share']),
                    'is_win': is_win,
                    'leader': row.get('leader_address', 'unknown')[:10],  # First 10 chars
                })
        
        if not btc_up_trades:
            print("No BTCUSD UP trades found!")
            return
        
        # Analyze entry prices
        win_entries = [t['entry_price'] for t in btc_up_trades if t['is_win']]
        loss_entries = [t['entry_price'] for t in btc_up_trades if not t['is_win']]
        
        print("=" * 60)
        print("ENTRY PRICE ANALYSIS (BTCUSD UP)")
        print("=" * 60)
        print(f"\nTotal trades: {len(btc_up_trades)}")
        print(f"Wins: {len(win_entries)} ({len(win_entries)/len(btc_up_trades)*100:.1f}%)")
        print(f"Losses: {len(loss_entries)} ({len(loss_entries)/len(btc_up_trades)*100:.1f}%)")
        
        print("\n--- ENTRY PRICE STATS ---")
        print(f"Winning trades:")
        print(f"  Average entry: {statistics.mean(win_entries):.4f}")
        print(f"  Median entry:  {statistics.median(win_entries):.4f}")
        print(f"  Min entry:     {min(win_entries):.4f}")
        print(f"  Max entry:     {max(win_entries):.4f}")
        
        print(f"\nLosing trades:")
        print(f"  Average entry: {statistics.mean(loss_entries):.4f}")
        print(f"  Median entry:  {statistics.median(loss_entries):.4f}")
        print(f"  Min entry:     {min(loss_entries):.4f}")
        print(f"  Max entry:     {max(loss_entries):.4f}")
        
        # Bucket analysis
        print("\n--- ENTRY PRICE BUCKETS ---")
        buckets = [(0, 0.50), (0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.00)]
        for low, high in buckets:
            bucket_trades = [t for t in btc_up_trades if low <= t['entry_price'] < high]
            if bucket_trades:
                wins = sum(1 for t in bucket_trades if t['is_win'])
                win_rate = wins / len(bucket_trades) * 100
                avg_profit = statistics.mean([t['profit'] for t in bucket_trades])
                print(f"  {low:.2f}-{high:.2f}: n={len(bucket_trades):3d}, win%={win_rate:5.1f}, avg_pnl={avg_profit:+.4f}")

def analyze_leaders():
    """Analyze performance by leader."""
    with open(EXITS_CSV, newline='') as f:
        reader = csv.DictReader(f)
        
        leader_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'pnl': 0.0})
        
        for row in reader:
            if row['symbol'] == 'BTCUSD' and row['side'] == 'UP':
                leader = row.get('leader_address', 'unknown')[:10]
                is_win = win_logic(row['side'], row['exit_type'], row['profit_per_share'])
                profit = float(row['profit_per_share'])
                
                if is_win:
                    leader_stats[leader]['wins'] += 1
                else:
                    leader_stats[leader]['losses'] += 1
                leader_stats[leader]['pnl'] += profit
        
        print("\n" + "=" * 60)
        print("LEADER PERFORMANCE ANALYSIS (BTCUSD UP)")
        print("=" * 60)
        
        # Sort by total trades
        leaders_sorted = sorted(leader_stats.items(), key=lambda x: x[1]['wins'] + x[1]['losses'], reverse=True)
        
        print(f"\n{'Leader':<12} {'Trades':>6} {'Win%':>6} {'Total PnL':>10}")
        print("-" * 40)
        
        for leader, stats in leaders_sorted[:20]:  # Top 20 leaders
            total = stats['wins'] + stats['losses']
            win_pct = stats['wins'] / total * 100 if total > 0 else 0
            print(f"{leader:<12} {total:>6} {win_pct:>5.1f}% {stats['pnl']:>+10.4f}")

def analyze_profit_distribution():
    """Analyze profit distribution for wins and losses."""
    with open(EXITS_CSV, newline='') as f:
        reader = csv.DictReader(f)
        
        win_profits = []
        loss_profits = []
        
        for row in reader:
            if row['symbol'] == 'BTCUSD' and row['side'] == 'UP':
                is_win = win_logic(row['side'], row['exit_type'], row['profit_per_share'])
                profit = float(row['profit_per_share'])
                
                if is_win:
                    win_profits.append(profit)
                else:
                    loss_profits.append(profit)
        
        print("\n" + "=" * 60)
        print("PROFIT DISTRIBUTION (BTCUSD UP)")
        print("=" * 60)
        
        print(f"\nWinning trades:")
        print(f"  Average profit: {statistics.mean(win_profits):+.4f}")
        print(f"  Median profit:  {statistics.median(win_profits):+.4f}")
        print(f"  Best win:       {max(win_profits):+.4f}")
        print(f"  Worst win:      {min(win_profits):+.4f}")
        
        print(f"\nLosing trades:")
        print(f"  Average loss:   {statistics.mean(loss_profits):+.4f}")
        print(f"  Median loss:    {statistics.median(loss_profits):+.4f}")
        print(f"  Best loss:      {max(loss_profits):+.4f}")
        print(f"  Worst loss:     {min(loss_profits):+.4f}")
        
        # Risk/reward ratio
        avg_win = statistics.mean(win_profits)
        avg_loss = abs(statistics.mean(loss_profits))
        print(f"\nRisk/Reward Ratio: {avg_win/avg_loss:.2f}:1")

if __name__ == "__main__":
    analyze_entry_prices()
    analyze_leaders()
    analyze_profit_distribution()
