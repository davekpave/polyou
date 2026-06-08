#!/usr/bin/env python3
"""
Analyze trade data to identify tuning opportunities for better performance.
"""

import csv
from pathlib import Path
from collections import defaultdict

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
                    pnl_str = pnl_str.lstrip('+').lstrip('-')
                    pnl = float(pnl_str)
                    if row.get('true_pnl', '0').strip().startswith('-'):
                        pnl = -pnl
                
                entry_price = float(row.get('entry_price', 0))
                
                trades.append({
                    'leader': row['leader_address'],
                    'pnl': pnl,
                    'won': row.get('actual_won', '').lower() == 'true',
                    'entry_price': entry_price,
                    'symbol': row.get('symbol', ''),
                    'side': row.get('side', '')
                })
            except (ValueError, KeyError) as e:
                continue
    return trades

def analyze_by_leader_volume(trades):
    """Group leaders by trade volume and analyze efficiency"""
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
    
    # Group by volume
    volume_groups = {
        'high_volume': [],  # 100+ trades
        'medium_volume': [],  # 20-99 trades
        'low_volume': []  # 5-19 trades
    }
    
    for leader, data in stats.items():
        if data['trades'] < 5:
            continue
        
        efficiency = data['total_pnl'] / data['trades'] if data['trades'] > 0 else 0
        win_rate = data['wins'] / data['trades'] * 100 if data['trades'] > 0 else 0
        
        leader_data = {
            'leader': leader,
            'trades': data['trades'],
            'pnl': data['total_pnl'],
            'efficiency': efficiency,
            'win_rate': win_rate
        }
        
        if data['trades'] >= 100:
            volume_groups['high_volume'].append(leader_data)
        elif data['trades'] >= 20:
            volume_groups['medium_volume'].append(leader_data)
        else:
            volume_groups['low_volume'].append(leader_data)
    
    return volume_groups

def analyze_by_entry_price(trades):
    """Analyze win rate by entry price ranges"""
    price_buckets = {
        '0.50-0.59': {'wins': 0, 'losses': 0, 'pnl': 0},
        '0.60-0.69': {'wins': 0, 'losses': 0, 'pnl': 0},
        '0.70-0.79': {'wins': 0, 'losses': 0, 'pnl': 0},
        '0.80-0.89': {'wins': 0, 'losses': 0, 'pnl': 0},
        '0.90-0.95': {'wins': 0, 'losses': 0, 'pnl': 0},
    }
    
    for trade in trades:
        price = trade['entry_price']
        if 0.50 <= price < 0.60:
            bucket = '0.50-0.59'
        elif 0.60 <= price < 0.70:
            bucket = '0.60-0.69'
        elif 0.70 <= price < 0.80:
            bucket = '0.70-0.79'
        elif 0.80 <= price < 0.90:
            bucket = '0.80-0.89'
        elif 0.90 <= price <= 0.95:
            bucket = '0.90-0.95'
        else:
            continue
        
        if trade['won']:
            price_buckets[bucket]['wins'] += 1
        else:
            price_buckets[bucket]['losses'] += 1
        price_buckets[bucket]['pnl'] += trade['pnl']
    
    return price_buckets

def main():
    csv_path = Path(__file__).parent.parent / 'logs' / 'shadow_exits.csv'
    
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found")
        return
    
    trades = load_trades(csv_path)
    
    print("=" * 80)
    print("  TUNING OPPORTUNITIES ANALYSIS")
    print("=" * 80)
    print(f"Analyzing {len(trades)} trades\n")
    
    # Analysis 1: Leader volume efficiency
    volume_groups = analyze_by_leader_volume(trades)
    
    print("=" * 80)
    print("  1. LEADER EFFICIENCY BY VOLUME")
    print("=" * 80)
    
    for group_name, group_data in [
        ('HIGH VOLUME (100+ trades)', volume_groups['high_volume']),
        ('MEDIUM VOLUME (20-99 trades)', volume_groups['medium_volume']),
        ('LOW VOLUME (5-19 trades)', volume_groups['low_volume'])
    ]:
        if not group_data:
            continue
        
        print(f"\n{group_name}:")
        group_data.sort(key=lambda x: x['efficiency'], reverse=True)
        
        total_trades = sum(d['trades'] for d in group_data)
        total_pnl = sum(d['pnl'] for d in group_data)
        avg_efficiency = total_pnl / total_trades if total_trades > 0 else 0
        
        print(f"  Leaders: {len(group_data)} | Total Trades: {total_trades} | "
              f"Total P&L: ${total_pnl:.2f} | Avg $/Trade: ${avg_efficiency:.3f}\n")
        
        print(f"{'Leader':<20} {'Trades':<8} {'P&L':<10} {'$/Trade':<10} {'Win%':<8}")
        print("-" * 70)
        for leader in group_data[:5]:  # Top 5 in each group
            print(f"{leader['leader']:<20} {leader['trades']:<8} "
                  f"${leader['pnl']:>8.2f} ${leader['efficiency']:>9.3f} {leader['win_rate']:>6.1f}%")
    
    # Analysis 2: Entry price performance
    price_buckets = analyze_by_entry_price(trades)
    
    print("\n" + "=" * 80)
    print("  2. PERFORMANCE BY ENTRY PRICE")
    print("=" * 80)
    print(f"\n{'Price Range':<15} {'Trades':<10} {'Win%':<10} {'P&L':<12} {'$/Trade':<10}")
    print("-" * 80)
    
    for price_range, data in price_buckets.items():
        total = data['wins'] + data['losses']
        if total == 0:
            continue
        win_rate = data['wins'] / total * 100
        efficiency = data['pnl'] / total if total > 0 else 0
        print(f"{price_range:<15} {total:<10} {win_rate:>8.1f}% ${data['pnl']:>10.2f} ${efficiency:>9.3f}")
    
    # Recommendations
    print("\n" + "=" * 80)
    print("  IMMEDIATE TUNING RECOMMENDATIONS")
    print("=" * 80)
    
    # Check if high-volume leaders are efficient
    high_vol = volume_groups['high_volume']
    if high_vol:
        high_vol.sort(key=lambda x: x['efficiency'], reverse=True)
        inefficient_high_vol = [l for l in high_vol if l['efficiency'] < 0.03]
        
        if inefficient_high_vol:
            print("\n⚠️  HIGH-VOLUME BUT LOW-EFFICIENCY LEADERS:")
            print("   These leaders trade a lot but contribute little profit.")
            for leader in inefficient_high_vol:
                print(f"   • {leader['leader'][:10]}... {leader['trades']} trades, "
                      f"${leader['pnl']:.2f}, ${leader['efficiency']:.3f}/trade")
            print("   → Consider reducing top_n to focus on quality over quantity")
    
    # Check entry price performance
    high_price_trades = price_buckets.get('0.90-0.95', {})
    high_price_total = high_price_trades['wins'] + high_price_trades['losses']
    if high_price_total > 0:
        high_price_winrate = high_price_trades['wins'] / high_price_total * 100
        high_price_efficiency = high_price_trades['pnl'] / high_price_total
        
        print(f"\n📊 HIGH-PRICE ENTRIES (0.90-0.95):")
        print(f"   Trades: {high_price_total}, Win Rate: {high_price_winrate:.1f}%, "
              f"Efficiency: ${high_price_efficiency:.3f}/trade")
        
        if high_price_efficiency < 0.03:
            print("   ⚠️  Low efficiency on high-price entries")
            print("   → Consider lowering max_entry_price to 0.85 or 0.80")
    
    # Top_n recommendation
    print("\n🎯 TOP_N PARAMETER:")
    print(f"   Current: 40 leaders")
    
    all_leaders = high_vol + volume_groups['medium_volume'] + volume_groups['low_volume']
    profitable = [l for l in all_leaders if l['pnl'] > 0]
    print(f"   Profitable leaders (5+ trades): {len(profitable)}/{len(all_leaders)}")
    
    if len(profitable) < 20:
        print(f"   → Recommend reducing top_n to 15-20 to focus on quality")
        print(f"      Current top 9 leaders account for most of your profit")
    
    print("\n" + "=" * 80)

if __name__ == '__main__':
    main()
