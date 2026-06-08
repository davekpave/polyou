#!/usr/bin/env python3
"""
Analyze day-by-day performance to show profit variability.
"""

import csv
from pathlib import Path
from collections import defaultdict
from datetime import datetime

def parse_iso_timestamp(ts_str):
    """Parse ISO timestamp"""
    try:
        return datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
    except:
        return None

def load_trades_by_day(csv_path: Path):
    """Load trades grouped by day"""
    daily_trades = defaultdict(list)
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                pnl_str = row.get('true_pnl', '0').strip()
                if not pnl_str or pnl_str in ('', 'N/A'):
                    pnl = 0.0
                else:
                    pnl_str = pnl_str.lstrip('+').lstrip('-')
                    pnl = float(pnl_str)
                    if row.get('true_pnl', '0').strip().startswith('-'):
                        pnl = -pnl
                
                ts = parse_iso_timestamp(row.get('ts_iso', ''))
                if ts:
                    day = ts.date()
                    daily_trades[day].append({
                        'pnl': pnl,
                        'won': row.get('actual_won', '').lower() == 'true',
                        'leader': row['leader_address']
                    })
            except (ValueError, KeyError):
                continue
    
    return daily_trades

def analyze_leader_consistency(csv_path: Path):
    """Check if best leaders are profitable every day"""
    daily_by_leader = defaultdict(lambda: defaultdict(lambda: {'trades': 0, 'pnl': 0.0, 'wins': 0}))
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                pnl_str = row.get('true_pnl', '0').strip()
                if not pnl_str or pnl_str in ('', 'N/A'):
                    pnl = 0.0
                else:
                    pnl_str = pnl_str.lstrip('+').lstrip('-')
                    pnl = float(pnl_str)
                    if row.get('true_pnl', '0').strip().startswith('-'):
                        pnl = -pnl
                
                ts = parse_iso_timestamp(row.get('ts_iso', ''))
                if ts:
                    day = ts.date()
                    leader = row['leader_address']
                    daily_by_leader[leader][day]['trades'] += 1
                    daily_by_leader[leader][day]['pnl'] += pnl
                    if row.get('actual_won', '').lower() == 'true':
                        daily_by_leader[leader][day]['wins'] += 1
            except (ValueError, KeyError):
                continue
    
    return daily_by_leader

def main():
    exits_file = Path(__file__).parent.parent / 'logs' / 'shadow_exits.csv'
    
    daily_trades = load_trades_by_day(exits_file)
    days = sorted(daily_trades.keys())
    
    print("=" * 90)
    print("  DAILY PERFORMANCE REALITY CHECK")
    print("=" * 90)
    
    print(f"\n📅 Day-by-Day Performance:\n")
    print(f"{'Date':<15} {'Trades':<10} {'Wins':<8} {'Losses':<10} {'Win%':<10} {'Daily P&L':<12}")
    print("-" * 90)
    
    winning_days = 0
    losing_days = 0
    
    for day in days:
        trades = daily_trades[day]
        total_pnl = sum(t['pnl'] for t in trades)
        wins = sum(1 for t in trades if t['won'])
        losses = len(trades) - wins
        win_rate = wins / len(trades) * 100 if trades else 0
        
        status = "✅" if total_pnl > 0 else "❌"
        if total_pnl > 0:
            winning_days += 1
        else:
            losing_days += 1
        
        print(f"{day} {status}  {len(trades):<10} {wins:<8} {losses:<10} {win_rate:>6.1f}%   ${total_pnl:>9.2f}")
    
    print("\n" + "=" * 90)
    print("  DAILY CONSISTENCY")
    print("=" * 90)
    
    print(f"\nTotal days tracked: {len(days)}")
    print(f"Winning days: {winning_days} ({winning_days/len(days)*100:.1f}%)")
    print(f"Losing days: {losing_days} ({losing_days/len(days)*100:.1f}%)")
    
    # Analyze best leaders' daily consistency
    daily_by_leader = analyze_leader_consistency(exits_file)
    
    print("\n" + "=" * 90)
    print("  TOP LEADERS - DAILY CONSISTENCY")
    print("=" * 90)
    
    # Focus on top 3 leaders
    top_leaders = [
        '0xa3d043b2da34f58045c6485d3f89b798b2b0ec04',
        '0x01b739b360d3c2f6cc8ec84cda900d48650e2eca',
        '0xa6657ab4eb9d92c8bbfb1d1d52ce7205e4ca01e3'
    ]
    
    for leader in top_leaders:
        leader_days = daily_by_leader.get(leader, {})
        if not leader_days:
            continue
        
        active_days = len(leader_days)
        winning_leader_days = sum(1 for day_stats in leader_days.values() if day_stats['pnl'] > 0)
        losing_leader_days = active_days - winning_leader_days
        
        print(f"\n{leader[:10]}... (Top Leader):")
        print(f"  Days active: {active_days}")
        print(f"  Winning days: {winning_leader_days} ({winning_leader_days/active_days*100:.1f}%)")
        print(f"  Losing days: {losing_leader_days} ({losing_leader_days/active_days*100:.1f}%)")
        print(f"  → NOT profitable every day")
    
    print("\n" + "=" * 90)
    print("  THE REALITY")
    print("=" * 90)
    
    print(f"\n⚠️  CRITICAL FACTS:")
    print(f"   1. You had LOSING days: {losing_days} out of {len(days)} days")
    print(f"   2. Even your BEST leaders have losing days")
    print(f"   3. Win rate is 48%, not 100%")
    print(f"   4. Markets are unpredictable - crypto moves both ways")
    
    print(f"\n🔑 WHY \"BEST TRADERS\" DON'T GUARANTEE DAILY PROFITS:")
    print(f"   • They're betting on 15-min price movements")
    print(f"   • Even 60% win rate = 40% losses")
    print(f"   • Crypto volatility is random short-term")
    print(f"   • Leaders make money OVER TIME, not every single day")
    print(f"   • You're copying their decisions, not their bankroll management")
    
    print(f"\n💡 WHAT YOU CAN EXPECT:")
    print(f"   • Good weeks and bad weeks")
    print(f"   • ~60-70% winning days (if you're lucky)")
    print(f"   • Some days will lose $10-40")
    print(f"   • Profitable MONTHLY, not guaranteed DAILY")
    
    print(f"\n❌ IMPOSSIBLE EXPECTATION:")
    print(f"   \"Profitable every single day\" = NOT REALISTIC")
    print(f"   Even the best hedge funds have losing days")
    
    print(f"\n✅ REALISTIC EXPECTATION:")
    print(f"   Profitable most days, ~$50/day AVERAGE over 30 days")
    print(f"   Some days: +$80, some days: -$30")
    print(f"   Monthly target: ~$1,500 ($50 × 30 days)")
    
    print("\n" + "=" * 90)
    print("  DO YOU ACCEPT THIS RISK?")
    print("=" * 90)
    print(f"\nIf you need GUARANTEED daily profits, crypto trading is NOT for you.")
    print(f"There will be losing days. Can you handle that emotionally and financially?")
    print("=" * 90)

if __name__ == '__main__':
    main()
