#!/usr/bin/env python3
"""
Check if leader rank correlates with actual performance.
"""

import csv
from pathlib import Path
from collections import defaultdict

def load_leaders_ranking(csv_path: Path):
    """Load leader rankings from oos_top_traders.csv"""
    rankings = {}
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, 1):
            rankings[row['address']] = i
    return rankings

def load_actual_performance(csv_path: Path):
    """Load actual performance from shadow_exits.csv"""
    stats = defaultdict(lambda: {'trades': 0, 'pnl': 0.0})
    
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
                
                leader = row['leader_address']
                stats[leader]['trades'] += 1
                stats[leader]['pnl'] += pnl
            except (ValueError, KeyError):
                continue
    
    return stats

def main():
    leaders_file = Path(__file__).parent.parent / 'logs' / 'oos_top_traders.csv'
    exits_file = Path(__file__).parent.parent / 'logs' / 'shadow_exits.csv'
    
    rankings = load_leaders_ranking(leaders_file)
    performance = load_actual_performance(exits_file)
    
    # Map leaders with both rank and performance
    leader_data = []
    for leader, perf in performance.items():
        if perf['trades'] >= 5:  # Only leaders with significant activity
            rank = rankings.get(leader, 999)
            leader_data.append({
                'leader': leader,
                'rank': rank,
                'trades': perf['trades'],
                'pnl': perf['pnl'],
                'efficiency': perf['pnl'] / perf['trades']
            })
    
    leader_data.sort(key=lambda x: x['pnl'], reverse=True)
    
    print("=" * 90)
    print("  RANK vs ACTUAL PERFORMANCE")
    print("=" * 90)
    print(f"\n{'Leader':<20} {'Rank':<8} {'Trades':<8} {'Actual P&L':<12} {'$/Trade':<10}")
    print("-" * 90)
    
    for leader in leader_data:
        rank_str = f"#{leader['rank']}" if leader['rank'] < 999 else "N/A"
        print(f"{leader['leader']:<20} {rank_str:<8} {leader['trades']:<8} "
              f"${leader['pnl']:>10.2f} ${leader['efficiency']:>9.3f}")
    
    # Analysis
    print("\n" + "=" * 90)
    print("  TOP 15 vs TOP 40 ANALYSIS")
    print("=" * 90)
    
    top_15_leaders = [l for l in leader_data if l['rank'] <= 15]
    top_40_leaders = [l for l in leader_data if l['rank'] <= 40]
    outside_40 = [l for l in leader_data if l['rank'] > 40]
    
    top_15_pnl = sum(l['pnl'] for l in top_15_leaders)
    top_40_pnl = sum(l['pnl'] for l in top_40_leaders)
    rank_16_40_pnl = sum(l['pnl'] for l in leader_data if 16 <= l['rank'] <= 40)
    outside_40_pnl = sum(l['pnl'] for l in outside_40)
    
    top_15_trades = sum(l['trades'] for l in top_15_leaders)
    rank_16_40_trades = sum(l['trades'] for l in leader_data if 16 <= l['rank'] <= 40)
    
    print(f"\nTop 15 ranked leaders:")
    print(f"  Leaders active: {len(top_15_leaders)}")
    print(f"  Total trades: {top_15_trades}")
    print(f"  Total P&L: ${top_15_pnl:.2f}")
    print(f"  Avg $/trade: ${top_15_pnl/top_15_trades:.3f}" if top_15_trades > 0 else "")
    
    print(f"\nRanked 16-40 leaders:")
    print(f"  Leaders active: {len([l for l in leader_data if 16 <= l['rank'] <= 40])}")
    print(f"  Total trades: {rank_16_40_trades}")
    print(f"  Total P&L: ${rank_16_40_pnl:.2f}")
    print(f"  Avg $/trade: ${rank_16_40_pnl/rank_16_40_trades:.3f}" if rank_16_40_trades > 0 else "")
    
    print("\n" + "=" * 90)
    print("  ⚠️  CRITICAL FINDING")
    print("=" * 90)
    
    # Find best performers outside top 15
    best_outside_top15 = [l for l in leader_data if l['rank'] > 15 and l['pnl'] > 5]
    if best_outside_top15:
        print(f"\n🚨 TOP PERFORMERS that would be CUT if top_n=15:")
        for leader in best_outside_top15[:5]:
            print(f"   • Rank #{leader['rank']}: {leader['leader'][:10]}... "
                  f"${leader['pnl']:.2f} ({leader['trades']} trades)")
        print(f"\n   You would LOSE ${sum(l['pnl'] for l in best_outside_top15):.2f} in profit!")
    
    # Find worst performers in top 15
    worst_in_top15 = [l for l in leader_data if l['rank'] <= 15 and l['pnl'] < 0]
    if worst_in_top15:
        print(f"\n⚠️  LOSING leaders in TOP 15 ranks:")
        for leader in worst_in_top15:
            print(f"   • Rank #{leader['rank']}: {leader['leader'][:10]}... "
                  f"${leader['pnl']:.2f} ({leader['trades']} trades)")
    
    print("\n" + "=" * 90)
    print("  CONCLUSION")
    print("=" * 90)
    
    if rank_16_40_pnl > 0 and len(best_outside_top15) > 0:
        print("\n❌ Reducing top_n would be COUNTERPRODUCTIVE!")
        print("   Historical rank does NOT predict current performance.")
        print("   Some of your best performers are ranked 16-40.")
    else:
        print("\n✅ Reducing top_n could help eliminate low performers.")
    
    print("=" * 90)

if __name__ == '__main__':
    main()
