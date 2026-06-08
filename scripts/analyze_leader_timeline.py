#!/usr/bin/env python3
"""Analyze a specific leader's day-by-day performance."""

import csv
import sys
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
    if len(sys.argv) < 2:
        print("Usage: python analyze_leader_timeline.py <leader_address>")
        sys.exit(1)
    
    target_leader = sys.argv[1].lower()
    
    trades_by_date = defaultdict(list)  # date_str -> list of (timestamp, pnl)
    
    with open(SHADOW_EXITS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            leader = row.get("leader_address", "").lower()
            if not leader.startswith(target_leader):
                continue
            
            ts_iso = row.get("ts_iso", "")
            dt = parse_iso_timestamp(ts_iso)
            if not dt:
                continue
            
            date_str = dt.strftime("%Y-%m-%d")
            
            try:
                pnl = float(row.get("true_pnl", "0") or "0")
                trades_by_date[date_str].append((dt, pnl))
            except (ValueError, TypeError):
                continue
    
    if not trades_by_date:
        print(f"No trades found for leader {target_leader}")
        sys.exit(1)
    
    # Sort by date
    sorted_dates = sorted(trades_by_date.keys())
    
    print("=" * 100)
    print(f"  DAILY PERFORMANCE TIMELINE - {target_leader}")
    print("=" * 100)
    print()
    
    print(f"{'Date':<12} {'Trades':<8} {'Daily P&L':<12} {'Cumulative P&L':<15} {'Win Rate':<10} {'Status'}")
    print("-" * 100)
    
    cumulative_pnl = 0.0
    unprofitable_days = 0
    total_days = 0
    days_in_red = []
    days_in_green = []
    
    for date_str in sorted_dates:
        trades = trades_by_date[date_str]
        daily_pnl = sum(pnl for _, pnl in trades)
        cumulative_pnl += daily_pnl
        
        wins = sum(1 for _, pnl in trades if pnl > 0)
        win_rate = (wins / len(trades) * 100) if trades else 0
        
        status = "📈 GREEN" if daily_pnl > 0 else "📉 RED" if daily_pnl < 0 else "➖ FLAT"
        cumul_status = "✅ Profit" if cumulative_pnl > 0 else "❌ Loss" if cumulative_pnl < 0 else "⚪ Break-even"
        
        print(f"{date_str:<12} {len(trades):<8} ${daily_pnl:>9.2f}    ${cumulative_pnl:>11.2f}    {win_rate:>5.1f}%     {status}")
        
        total_days += 1
        if cumulative_pnl < 0:
            unprofitable_days += 1
            days_in_red.append(date_str)
        else:
            days_in_green.append(date_str)
    
    print()
    print("=" * 100)
    print("  SUMMARY")
    print("=" * 100)
    print()
    
    total_trades = sum(len(trades) for trades in trades_by_date.values())
    total_pnl = cumulative_pnl
    
    print(f"Total Trading Days:     {total_days}")
    print(f"Days in Cumulative RED: {unprofitable_days} ({unprofitable_days/total_days*100:.1f}%)")
    print(f"Days in Cumulative GREEN: {len(days_in_green)} ({len(days_in_green)/total_days*100:.1f}%)")
    print()
    print(f"Total Trades:           {total_trades}")
    print(f"Final P&L:              ${total_pnl:.2f}")
    print()
    
    if unprofitable_days > 0 and len(days_in_green) > 0:
        first_green_day = days_in_green[0]
        print(f"Turned profitable on:   {first_green_day}")
        print(f"Days to profitability:  {unprofitable_days}")
    
    print("=" * 100)

if __name__ == "__main__":
    main()
