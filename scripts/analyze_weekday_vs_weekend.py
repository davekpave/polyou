#!/usr/bin/env python3
"""Analyze bot performance by day of week."""

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
    trades_by_day = defaultdict(list)  # day_name -> list of pnl values
    
    with open(SHADOW_EXITS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts_iso = row.get("ts_iso", "")
            dt = parse_iso_timestamp(ts_iso)
            if not dt:
                continue
            
            day_name = dt.strftime("%A")  # Monday, Tuesday, etc.
            
            try:
                pnl = float(row.get("true_pnl", "0") or "0")
                trades_by_day[day_name].append(pnl)
            except (ValueError, TypeError):
                continue
    
    # Order by day of week
    day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    
    print("=" * 80)
    print("  WEEKDAY vs WEEKEND PERFORMANCE ANALYSIS")
    print("=" * 80)
    print()
    
    weekday_trades = []
    weekend_trades = []
    
    print("Daily Breakdown:")
    print(f"{'Day':<12} {'Trades':<8} {'Total P&L':<12} {'Avg/Trade':<12} {'Win Rate'}")
    print("-" * 80)
    
    for day in day_order:
        if day not in trades_by_day:
            continue
        
        trades = trades_by_day[day]
        total_pnl = sum(trades)
        avg_per_trade = total_pnl / len(trades) if trades else 0
        wins = sum(1 for pnl in trades if pnl > 0)
        win_rate = (wins / len(trades) * 100) if trades else 0
        
        print(f"{day:<12} {len(trades):<8} ${total_pnl:>9.2f}    ${avg_per_trade:>8.4f}    {win_rate:>5.1f}%")
        
        # Accumulate for weekday/weekend totals
        if day in ["Saturday", "Sunday"]:
            weekend_trades.extend(trades)
        else:
            weekday_trades.extend(trades)
    
    print()
    print("=" * 80)
    print("  WEEKDAY vs WEEKEND SUMMARY")
    print("=" * 80)
    print()
    
    # Weekday stats
    if weekday_trades:
        weekday_total = sum(weekday_trades)
        weekday_avg = weekday_total / len(weekday_trades)
        weekday_wins = sum(1 for pnl in weekday_trades if pnl > 0)
        weekday_win_rate = (weekday_wins / len(weekday_trades) * 100)
        
        print(f"WEEKDAYS (Mon-Fri):")
        print(f"  Trades:        {len(weekday_trades)}")
        print(f"  Total P&L:     ${weekday_total:.2f}")
        print(f"  Avg per Trade: ${weekday_avg:.4f}")
        print(f"  Win Rate:      {weekday_win_rate:.1f}%")
        print()
    
    # Weekend stats
    if weekend_trades:
        weekend_total = sum(weekend_trades)
        weekend_avg = weekend_total / len(weekend_trades)
        weekend_wins = sum(1 for pnl in weekend_trades if pnl > 0)
        weekend_win_rate = (weekend_wins / len(weekend_trades) * 100)
        
        print(f"WEEKENDS (Sat-Sun):")
        print(f"  Trades:        {len(weekend_trades)}")
        print(f"  Total P&L:     ${weekend_total:.2f}")
        print(f"  Avg per Trade: ${weekend_avg:.4f}")
        print(f"  Win Rate:      {weekend_win_rate:.1f}%")
        print()
    
    # Comparison
    if weekday_trades and weekend_trades:
        print("=" * 80)
        print("  COMPARISON")
        print("=" * 80)
        print()
        
        better = "WEEKDAYS" if weekday_avg > weekend_avg else "WEEKENDS"
        diff = abs(weekday_avg - weekend_avg)
        pct_diff = (diff / min(weekday_avg, weekend_avg) * 100) if min(weekday_avg, weekend_avg) > 0 else 0
        
        print(f"Better performer: {better}")
        print(f"Difference:       ${diff:.4f} per trade ({pct_diff:.1f}% better)")
        print()
        
        if weekday_win_rate > weekend_win_rate:
            print(f"Win rate higher on weekdays: {weekday_win_rate:.1f}% vs {weekend_win_rate:.1f}%")
        else:
            print(f"Win rate higher on weekends: {weekend_win_rate:.1f}% vs {weekday_win_rate:.1f}%")
    
    print("=" * 80)

if __name__ == "__main__":
    main()
