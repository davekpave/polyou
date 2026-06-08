#!/usr/bin/env python3
"""
Analyze if expanding beyond top_n=40 leaders would improve performance.
"""

import csv
from pathlib import Path
from collections import defaultdict

def load_leaders_ranking(csv_path: Path):
    """Load leader rankings from oos_top_traders.csv"""
    rankings = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rankings.append(row['address'])
    return rankings

def load_actual_performance(csv_path: Path):
    """Load actual performance from shadow_exits.csv"""
    stats = defaultdict(lambda: {'trades': 0, 'pnl': 0.0, 'wins': 0, 'losses': 0})
    
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
                if row.get('actual_won', '').lower() == 'true':
                    stats[leader]['wins'] += 1
                else:
                    stats[leader]['losses'] += 1
            except (ValueError, KeyError):
                continue
    
    return stats

def main():
    leaders_file = Path(__file__).parent.parent / 'logs' / 'oos_top_traders.csv'
    exits_file = Path(__file__).parent.parent / 'logs' / 'shadow_exits.csv'
    
    rankings = load_leaders_ranking(leaders_file)
    performance = load_actual_performance(exits_file)
    
    print("=" * 90)
    print("  EXPANSION ANALYSIS: Should we increase top_n beyond 40?")
    print("=" * 90)
    
    # Analyze current top 40
    top_40 = rankings[:40]
    active_in_top_40 = [addr for addr in top_40 if performance.get(addr, {}).get('trades', 0) >= 1]
    profitable_in_top_40 = [addr for addr in top_40 if performance.get(addr, {}).get('pnl', 0) > 0 and performance.get(addr, {}).get('trades', 0) >= 5]
    
    top_40_trades = sum(performance.get(addr, {}).get('trades', 0) for addr in top_40)
    top_40_pnl = sum(performance.get(addr, {}).get('pnl', 0) for addr in top_40)
    
    print(f"\n📊 Current Top 40 Status:")
    print(f"   Active (1+ trade): {len(active_in_top_40)}/40 ({len(active_in_top_40)/40*100:.0f}%)")
    print(f"   Profitable (5+ trades, +P&L): {len(profitable_in_top_40)}/40")
    print(f"   Total trades: {top_40_trades}")
    print(f"   Total P&L: ${top_40_pnl:.2f}")
    print(f"   Avg $/trade: ${top_40_pnl/top_40_trades:.3f}" if top_40_trades > 0 else "")
    
    # Analyze ranks 41-60
    if len(rankings) >= 60:
        ranks_41_60 = rankings[40:60]
        active_41_60 = [addr for addr in ranks_41_60 if performance.get(addr, {}).get('trades', 0) >= 1]
        profitable_41_60 = [addr for addr in ranks_41_60 if performance.get(addr, {}).get('pnl', 0) > 0 and performance.get(addr, {}).get('trades', 0) >= 5]
        
        trades_41_60 = sum(performance.get(addr, {}).get('trades', 0) for addr in ranks_41_60)
        pnl_41_60 = sum(performance.get(addr, {}).get('pnl', 0) for addr in ranks_41_60)
        
        print(f"\n📈 Ranks 41-60 (potential expansion):")
        print(f"   Active (1+ trade): {len(active_41_60)}/20")
        print(f"   Profitable (5+ trades, +P&L): {len(profitable_41_60)}/20")
        print(f"   Total trades: {trades_41_60}")
        print(f"   Total P&L: ${pnl_41_60:.2f}")
        print(f"   Avg $/trade: ${pnl_41_60/trades_41_60:.3f}" if trades_41_60 > 0 else "   Avg $/trade: N/A")
    
    # Find all active leaders outside top 40
    all_active_leaders = [addr for addr, stats in performance.items() if stats['trades'] >= 5]
    outside_top_40 = [addr for addr in all_active_leaders if addr not in top_40]
    
    print(f"\n🔍 All Active Leaders Analysis:")
    print(f"   Total unique leaders with 5+ trades: {len(all_active_leaders)}")
    print(f"   Leaders outside top 40: {len(outside_top_40)}")
    
    if outside_top_40:
        # Find profitable ones outside top 40
        profitable_outside = [(addr, performance[addr]['pnl'], performance[addr]['trades']) 
                              for addr in outside_top_40 
                              if performance[addr]['pnl'] > 0]
        profitable_outside.sort(key=lambda x: x[1], reverse=True)
        
        if profitable_outside:
            total_missed_pnl = sum(p[1] for p in profitable_outside)
            total_missed_trades = sum(p[2] for p in profitable_outside)
            
            print(f"\n⚠️  PROFITABLE LEADERS WE'RE MISSING:")
            print(f"   Count: {len(profitable_outside)}")
            print(f"   Total P&L missed: ${total_missed_pnl:.2f}")
            print(f"   Total trades missed: {total_missed_trades}")
            print(f"   Avg $/trade: ${total_missed_pnl/total_missed_trades:.3f}" if total_missed_trades > 0 else "")
            
            print(f"\n   Top 5 missed opportunities:")
            print(f"   {'Leader':<44} {'Trades':<8} {'P&L':<10} {'$/Trade':<10}")
            print("   " + "-" * 80)
            for addr, pnl, trades in profitable_outside[:5]:
                efficiency = pnl / trades if trades > 0 else 0
                win_rate = performance[addr]['wins'] / trades * 100 if trades > 0 else 0
                print(f"   {addr:<44} {trades:<8} ${pnl:>8.2f} ${efficiency:>9.3f}")
        else:
            print(f"\n✅ No profitable leaders outside top 40 (with 5+ trades)")
    
    # Analyze expansion scenarios
    print("\n" + "=" * 90)
    print("  EXPANSION SCENARIOS")
    print("=" * 90)
    
    for top_n in [50, 60, 80, 100]:
        if len(rankings) < top_n:
            continue
            
        scenario_leaders = rankings[:top_n]
        scenario_trades = sum(performance.get(addr, {}).get('trades', 0) for addr in scenario_leaders)
        scenario_pnl = sum(performance.get(addr, {}).get('pnl', 0) for addr in scenario_leaders)
        
        added_leaders = rankings[40:top_n]
        added_trades = sum(performance.get(addr, {}).get('trades', 0) for addr in added_leaders)
        added_pnl = sum(performance.get(addr, {}).get('pnl', 0) for addr in added_leaders)
        
        print(f"\n📊 Scenario: top_n={top_n}")
        print(f"   Total P&L: ${scenario_pnl:.2f} ({added_pnl:+.2f} vs current)")
        print(f"   Total trades: {scenario_trades} (+{added_trades} vs current)")
        if added_trades > 0:
            print(f"   Added $/trade: ${added_pnl/added_trades:.3f}")
    
    print("\n" + "=" * 90)
    print("  RECOMMENDATION")
    print("=" * 90)
    
    if len(outside_top_40) > 0 and profitable_outside and total_missed_pnl > 5:
        print(f"\n✅ YES, consider expanding to top_n=50 or 60")
        print(f"   You're missing ${total_missed_pnl:.2f} from profitable leaders outside top 40")
        print(f"   These are likely new traders not in the OOS rankings")
    elif trades_41_60 > 0 and pnl_41_60 > 0:
        print(f"\n✅ YES, expand to top_n=50")
        print(f"   Ranks 41-60 show positive performance: ${pnl_41_60:.2f}")
    else:
        print(f"\n❌ NO, keep top_n=40")
        print(f"   No significant profit opportunity in ranks 41+")
        print(f"   Most active profitable leaders are already in top 40")
    
    print("=" * 90)

if __name__ == '__main__':
    main()
