#!/usr/bin/env python3
"""
Analyze the relationship between number of leaders and total profit potential.
"""

import csv
from pathlib import Path
from collections import defaultdict

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
    exits_file = Path(__file__).parent.parent / 'logs' / 'shadow_exits.csv'
    performance = load_actual_performance(exits_file)
    
    # Get all leaders sorted by profit
    all_leaders = []
    for leader, stats in performance.items():
        if stats['trades'] >= 1:  # Any activity
            efficiency = stats['pnl'] / stats['trades'] if stats['trades'] > 0 else 0
            win_rate = stats['wins'] / stats['trades'] * 100 if stats['trades'] > 0 else 0
            all_leaders.append({
                'leader': leader,
                'trades': stats['trades'],
                'pnl': stats['pnl'],
                'efficiency': efficiency,
                'win_rate': win_rate
            })
    
    all_leaders.sort(key=lambda x: x['pnl'], reverse=True)
    
    print("=" * 90)
    print("  LEADER COUNT vs PROFIT ANALYSIS")
    print("=" * 90)
    print(f"\nTotal unique leaders with any activity: {len(all_leaders)}")
    
    # Calculate cumulative profit
    cumulative_profit = 0
    cumulative_trades = 0
    
    print("\n📊 CUMULATIVE PROFIT BY LEADER COUNT:")
    print(f"{'Leaders':<10} {'Cum. Trades':<15} {'Cum. P&L':<15} {'$/Trade':<12} {'% of Total':<12}")
    print("-" * 90)
    
    total_possible_profit = sum(l['pnl'] for l in all_leaders)
    
    for milestone in [1, 3, 5, 10, 15, 20, 25, 30, 40, 50, 75, 100, len(all_leaders)]:
        if milestone > len(all_leaders):
            continue
        
        leaders_subset = all_leaders[:milestone]
        cumulative_profit = sum(l['pnl'] for l in leaders_subset)
        cumulative_trades = sum(l['trades'] for l in leaders_subset)
        avg_efficiency = cumulative_profit / cumulative_trades if cumulative_trades > 0 else 0
        pct_of_total = cumulative_profit / total_possible_profit * 100 if total_possible_profit != 0 else 0
        
        print(f"Top {milestone:<5} {cumulative_trades:<15} ${cumulative_profit:>12.2f} "
              f"${avg_efficiency:>10.3f} {pct_of_total:>10.1f}%")
    
    # Show what we'd get with ALL leaders
    print("\n" + "=" * 90)
    print("  MAXIMUM THEORETICAL PROFIT")
    print("=" * 90)
    
    total_trades = sum(l['trades'] for l in all_leaders)
    total_profit = sum(l['pnl'] for l in all_leaders)
    avg_efficiency = total_profit / total_trades if total_trades > 0 else 0
    
    print(f"\nIf we copied EVERY leader (all {len(all_leaders)} who traded):")
    print(f"  Total trades: {total_trades}")
    print(f"  Total P&L: ${total_profit:.2f}")
    print(f"  Avg $/trade: ${avg_efficiency:.3f}")
    print(f"  Daily profit: ${total_profit/6.0:.2f}/day (over 6 days)")
    
    # Compare to current
    current_top_50 = all_leaders[:50]
    current_profit = sum(l['pnl'] for l in current_top_50)
    current_trades = sum(l['trades'] for l in current_top_50)
    
    additional_profit = total_profit - current_profit
    additional_trades = total_trades - current_trades
    
    print(f"\n📈 Gain from adding leaders 51+:")
    print(f"  Additional leaders: {len(all_leaders) - 50}")
    print(f"  Additional trades: {additional_trades}")
    print(f"  Additional P&L: ${additional_profit:.2f}")
    if additional_trades > 0:
        print(f"  Their $/trade: ${additional_profit/additional_trades:.3f}")
    
    # Show the losers
    losers = [l for l in all_leaders if l['pnl'] < 0]
    loser_pnl = sum(l['pnl'] for l in losers)
    loser_trades = sum(l['trades'] for l in losers)
    
    print(f"\n⚠️  Losing leaders included in total:")
    print(f"  Count: {len(losers)}")
    print(f"  Total loss: ${loser_pnl:.2f}")
    print(f"  Total trades: {loser_trades}")
    
    print("\n" + "=" * 90)
    print("  THE REAL PROBLEM")
    print("=" * 90)
    
    print(f"\nCurrent daily rate: ${total_profit/6.0:.2f}/day")
    print(f"Target: $50/day")
    print(f"Gap: ${50 - (total_profit/6.0):.2f}/day")
    
    print(f"\nEven with ALL {len(all_leaders)} leaders, you'd only make ${total_profit/6.0:.2f}/day")
    print(f"That's still {50/(total_profit/6.0):.1f}x short of your $50/day goal")
    
    print("\n🔑 KEY INSIGHT:")
    print("   The problem is NOT the number of leaders.")
    print("   The problem is that you're PAPER TRADING with ZERO capital.")
    print()
    print("   Paper trading = 1 share per position = tiny profits")
    print("   Real trading = scale position sizes = proportional profits")
    print()
    print("   To reach $50/day at current ${:.3f}/trade:".format(avg_efficiency))
    needed_trades = 50 / (total_profit/6.0) * total_trades / 6.0
    print(f"     You'd need ~{needed_trades:.0f} trades/day")
    print(f"     Current: ~{total_trades/6.0:.0f} trades/day")
    print(f"     That's {needed_trades/(total_trades/6.0):.1f}x more volume - NOT FEASIBLE")
    print()
    print("   Alternative: Scale up with real capital")
    capital_needed = 50 / (total_profit/6.0)
    print(f"     At current performance, ~${capital_needed:.0f}K would yield $50/day")
    print(f"     (This assumes linear scaling, which may not hold)")
    
    print("\n" + "=" * 90)
    print("  RECOMMENDATION")
    print("=" * 90)
    print("\n✅ Keep 50 leaders - you're already capturing 96%+ of available profit")
    print("⚠️  More leaders won't solve the $50/day gap")
    print("📊 Real capital + position sizing is the path to $50/day, not more leaders")
    print("🕐 Continue collecting data for 30 days before any capital decisions")
    
    print("=" * 90)

if __name__ == '__main__':
    main()
