#!/usr/bin/env python3
"""Analyze bot performance by hour of day."""

import csv
from datetime import datetime
from collections import defaultdict

SHADOW_EXITS_CSV = "logs/shadow_exits.csv"

def parse_iso_timestamp(ts_iso):
    """Parse ISO timestamp to datetime."""
    if not ts_iso or ts_iso == "":
        return None
    try:
        return datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
    except ValueError:
        return None

def main():
    trades_by_hour = defaultdict(list)  # hour -> list of pnl values
    
    with open(SHADOW_EXITS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts_iso = row.get("ts_iso", "")
            dt = parse_iso_timestamp(ts_iso)
            if not dt:
                continue
            
            hour = dt.hour  # 0-23
            
            try:
                pnl = float(row.get("true_pnl", "0") or "0")
                trades_by_hour[hour].append(pnl)
            except (ValueError, TypeError):
                continue
    
    print("=" * 90)
    print("  TIME OF DAY PERFORMANCE ANALYSIS (24-Hour)")
    print("=" * 90)
    print()
    
    print(f"{'Hour':<10} {'Trades':<8} {'Total P&L':<12} {'Avg/Trade':<12} {'Win Rate':<10} {'Best':<10} {'Worst'}")
    print("-" * 90)
    
    total_all_trades = 0
    total_all_pnl = 0.0
    
    best_hour_data = None
    worst_hour_data = None
    
    for hour in range(24):
        if hour not in trades_by_hour:
            continue
        
        trades = trades_by_hour[hour]
        total_pnl = sum(trades)
        avg_per_trade = total_pnl / len(trades) if trades else 0
        wins = sum(1 for pnl in trades if pnl > 0)
        win_rate = (wins / len(trades) * 100) if trades else 0
        best = max(trades) if trades else 0
        worst = min(trades) if trades else 0
        
        # Format hour with AM/PM
        hour_str = f"{hour:02d}:00"
        ampm = "AM" if hour < 12 else "PM"
        display_hour = f"{hour % 12 if hour % 12 != 0 else 12}:00 {ampm}"
        
        print(f"{display_hour:<10} {len(trades):<8} ${total_pnl:>9.2f}    ${avg_per_trade:>8.4f}    {win_rate:>5.1f}%     ${best:>6.2f}    ${worst:>6.2f}")
        
        total_all_trades += len(trades)
        total_all_pnl += total_pnl
        
        # Track best/worst hours
        if best_hour_data is None or avg_per_trade > best_hour_data[1]:
            best_hour_data = (display_hour, avg_per_trade, len(trades), total_pnl)
        
        if worst_hour_data is None or avg_per_trade < worst_hour_data[1]:
            worst_hour_data = (display_hour, avg_per_trade, len(trades), total_pnl)
    
    print("-" * 90)
    print(f"{'TOTAL':<10} {total_all_trades:<8} ${total_all_pnl:>9.2f}    ${total_all_pnl/total_all_trades:>8.4f}")
    print()
    
    print("=" * 90)
    print("  KEY INSIGHTS")
    print("=" * 90)
    print()
    
    if best_hour_data:
        print(f"Most Profitable Hour: {best_hour_data[0]}")
        print(f"  Avg per Trade: ${best_hour_data[1]:.4f}")
        print(f"  Trades:        {best_hour_data[2]}")
        print(f"  Total P&L:     ${best_hour_data[3]:.2f}")
        print()
    
    if worst_hour_data:
        print(f"Least Profitable Hour: {worst_hour_data[0]}")
        print(f"  Avg per Trade: ${worst_hour_data[1]:.4f}")
        print(f"  Trades:        {worst_hour_data[2]}")
        print(f"  Total P&L:     ${worst_hour_data[3]:.2f}")
        print()
    
    # Analyze time blocks
    print("=" * 90)
    print("  TIME BLOCK ANALYSIS")
    print("=" * 90)
    print()
    
    time_blocks = {
        "Night (12 AM - 6 AM)": range(0, 6),
        "Morning (6 AM - 12 PM)": range(6, 12),
        "Afternoon (12 PM - 6 PM)": range(12, 18),
        "Evening (6 PM - 12 AM)": range(18, 24),
    }
    
    block_stats = []
    
    for block_name, hours in time_blocks.items():
        block_trades = []
        for hour in hours:
            if hour in trades_by_hour:
                block_trades.extend(trades_by_hour[hour])
        
        if block_trades:
            total_pnl = sum(block_trades)
            avg_pnl = total_pnl / len(block_trades)
            wins = sum(1 for pnl in block_trades if pnl > 0)
            win_rate = (wins / len(block_trades) * 100)
            
            block_stats.append((block_name, len(block_trades), total_pnl, avg_pnl, win_rate))
    
    # Sort by avg per trade
    block_stats.sort(key=lambda x: x[3], reverse=True)
    
    print(f"{'Time Block':<25} {'Trades':<8} {'Total P&L':<12} {'Avg/Trade':<12} {'Win Rate'}")
    print("-" * 90)
    
    for block_name, trades, total_pnl, avg_pnl, win_rate in block_stats:
        print(f"{block_name:<25} {trades:<8} ${total_pnl:>9.2f}    ${avg_pnl:>8.4f}    {win_rate:>5.1f}%")
    
    print()
    print("=" * 90)

if __name__ == "__main__":
    main()
