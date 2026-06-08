#!/usr/bin/env python3
"""
Check for leaders that are consistently losing money and may need to be blacklisted.
"""

import csv
from pathlib import Path
from collections import defaultdict
from datetime import datetime

def load_trades(csv_path: Path):
    """Load trades from shadow_exits.csv"""
    trades = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                pnl_str = row.get('true_pnl', '0').strip()
                if not pnl_str or pnl_str in ('', 'N/A'):
                    pnl = 0.0
                else:
                    # Remove +/- prefix if present
                    pnl_str = pnl_str.lstrip('+').lstrip('-')
                    pnl = float(pnl_str)
                    # Check original for sign
                    if row.get('true_pnl', '0').strip().startswith('-'):
                        pnl = -pnl
                
                trades.append({
                    'leader': row['leader_address'],
                    'pnl': pnl,
                    'won': row.get('actual_won', '').lower() == 'true'
                })
            except (ValueError, KeyError) as e:
                continue
    return trades

def analyze_leaders(trades):
    """Analyze per-leader statistics"""
    stats = defaultdict(lambda: {
        'trades': 0,
        'total_pnl': 0.0,
        'wins': 0,
        'losses': 0
    })
    
    for trade in trades:
        leader = trade['leader']
        stats[leader]['trades'] += 1
        stats[leader]['total_pnl'] += trade['pnl']
        if trade['won']:
            stats[leader]['wins'] += 1
        else:
            stats[leader]['losses'] += 1
    
    return stats

def main():
    csv_path = Path(__file__).parent.parent / 'logs' / 'shadow_exits.csv'
    
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found")
        return
    
    trades = load_trades(csv_path)
    stats = analyze_leaders(trades)
    
    # Filter for leaders with significant losses (5+ trades, negative P&L)
    losing_leaders = []
    for leader, data in stats.items():
        if data['trades'] >= 5 and data['total_pnl'] < -0.50:  # At least -$0.50
            win_rate = data['wins'] / data['trades'] * 100 if data['trades'] > 0 else 0
            avg_per_trade = data['total_pnl'] / data['trades'] if data['trades'] > 0 else 0
            losing_leaders.append({
                'leader': leader,
                'trades': data['trades'],
                'pnl': data['total_pnl'],
                'wins': data['wins'],
                'losses': data['losses'],
                'win_rate': win_rate,
                'avg_per_trade': avg_per_trade
            })
    
    # Sort by P&L (worst first)
    losing_leaders.sort(key=lambda x: x['pnl'])
    
    print("=" * 80)
    print("  LOSING LEADERS ANALYSIS")
    print("=" * 80)
    print(f"Criteria: 5+ trades AND total P&L < -$0.50")
    print(f"Found {len(losing_leaders)} leaders meeting criteria\n")
    
    if losing_leaders:
        print(f"{'Leader':<20} {'Trades':<8} {'Total P&L':<12} {'Wins':<6} {'Losses':<8} {'Win%':<8} {'$/Trade':<10}")
        print("-" * 80)
        for leader in losing_leaders:
            print(f"{leader['leader']:<20} {leader['trades']:<8} "
                  f"${leader['pnl']:>10.2f} {leader['wins']:<6} {leader['losses']:<8} "
                  f"{leader['win_rate']:>6.1f}% {leader['avg_per_trade']:>9.3f}")
    else:
        print("✅ No leaders found with significant consistent losses!")
        print("   All leaders with 5+ trades are either profitable or have minor losses.")
    
    print("\n" + "=" * 80)
    print("  BORDERLINE LEADERS (Minor Losses)")
    print("=" * 80)
    print("Leaders with 5+ trades and P&L between -$0.50 and $0:\n")
    
    # Show borderline cases
    borderline = []
    for leader, data in stats.items():
        if data['trades'] >= 5 and -0.50 <= data['total_pnl'] < 0:
            win_rate = data['wins'] / data['trades'] * 100 if data['trades'] > 0 else 0
            avg_per_trade = data['total_pnl'] / data['trades'] if data['trades'] > 0 else 0
            borderline.append({
                'leader': leader,
                'trades': data['trades'],
                'pnl': data['total_pnl'],
                'wins': data['wins'],
                'losses': data['losses'],
                'win_rate': win_rate,
                'avg_per_trade': avg_per_trade
            })
    
    borderline.sort(key=lambda x: x['pnl'])
    
    if borderline:
        print(f"{'Leader':<20} {'Trades':<8} {'Total P&L':<12} {'Wins':<6} {'Losses':<8} {'Win%':<8} {'$/Trade':<10}")
        print("-" * 80)
        for leader in borderline:
            print(f"{leader['leader']:<20} {leader['trades']:<8} "
                  f"${leader['pnl']:>10.2f} {leader['wins']:<6} {leader['losses']:<8} "
                  f"{leader['win_rate']:>6.1f}% {leader['avg_per_trade']:>9.3f}")
    else:
        print("No borderline leaders found.")
    
    print("\n" + "=" * 80)
    print("  RECOMMENDATION")
    print("=" * 80)
    
    if len(losing_leaders) == 0:
        print("✅ No additional blacklisting needed at this time.")
        print("   Continue monitoring leaders, especially borderline cases.")
    else:
        print("⚠️  Consider blacklisting the following leaders:")
        for i, leader in enumerate(losing_leaders[:5], 1):  # Show top 5 worst
            print(f"   {i}. {leader['leader']} (${leader['pnl']:.2f} over {leader['trades']} trades)")
    
    print("=" * 80)

if __name__ == '__main__':
    main()
