#!/usr/bin/env python3
"""
Weekly Status Check for Polyou Copy Trading Bot
Analyzes logs/shadow_exits.csv to track performance and leader consistency
"""

import csv
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple


def parse_iso_timestamp(ts_str: str) -> datetime:
    """Parse ISO timestamp string to datetime."""
    return datetime.fromisoformat(ts_str.replace('Z', '+00:00'))


def load_trades(csv_path: Path) -> List[Dict]:
    """Load all trades from shadow_exits.csv."""
    trades = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row['ts'] = parse_iso_timestamp(row['ts_iso'])
            # Parse true_pnl, handling both signed formats (+/-) and empty strings
            pnl_str = row.get('true_pnl', '').strip()
            if pnl_str and pnl_str not in ('', 'N/A'):
                row['true_pnl'] = float(pnl_str.replace('+', ''))
            else:
                row['true_pnl'] = 0.0
            trades.append(row)
    return trades


def analyze_leaders(trades: List[Dict], days_filter: int = None) -> Dict:
    """
    Analyze performance by leader address.
    
    Args:
        trades: List of trade dictionaries
        days_filter: If set, only include trades from last N days
    
    Returns:
        Dict mapping leader_address -> stats dict
    """
    now = datetime.now(trades[0]['ts'].tzinfo) if trades else datetime.now()
    cutoff = now - timedelta(days=days_filter) if days_filter else None
    
    leader_stats = defaultdict(lambda: {
        'trades': 0,
        'total_pnl': 0.0,
        'wins': 0,
        'losses': 0,
        'last_trade': None
    })
    
    for trade in trades:
        if cutoff and trade['ts'] < cutoff:
            continue
        
        leader = trade['leader_address']
        pnl = trade['true_pnl']
        
        leader_stats[leader]['trades'] += 1
        leader_stats[leader]['total_pnl'] += pnl
        if pnl > 0:
            leader_stats[leader]['wins'] += 1
        elif pnl < 0:
            leader_stats[leader]['losses'] += 1
        
        if leader_stats[leader]['last_trade'] is None or trade['ts'] > leader_stats[leader]['last_trade']:
            leader_stats[leader]['last_trade'] = trade['ts']
    
    return dict(leader_stats)


def format_leader_address(addr: str, length: int = 10) -> str:
    """Format leader address to first N characters."""
    return addr[:length] if addr else "unknown"


def print_header(title: str):
    """Print a formatted section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_leader_table(leader_stats: Dict, top_n: int = 10, title: str = "Top Leaders"):
    """Print a formatted table of leader statistics."""
    # Sort by total P&L descending
    sorted_leaders = sorted(
        leader_stats.items(),
        key=lambda x: x[1]['total_pnl'],
        reverse=True
    )[:top_n]
    
    print(f"\n{title}:")
    print(f"{'Leader':<12} {'Trades':>7} {'Total P&L':>10} {'Wins':>5} {'Losses':>7} {'Win%':>6} {'$/Trade':>9}")
    print("-" * 70)
    
    for leader_addr, stats in sorted_leaders:
        leader_short = format_leader_address(leader_addr)
        win_rate = (stats['wins'] / stats['trades'] * 100) if stats['trades'] > 0 else 0
        avg_per_trade = stats['total_pnl'] / stats['trades'] if stats['trades'] > 0 else 0
        
        print(f"{leader_short:<12} {stats['trades']:>7} {stats['total_pnl']:>10.2f} "
              f"{stats['wins']:>5} {stats['losses']:>7} {win_rate:>6.1f} {avg_per_trade:>9.3f}")


def main():
    workspace_root = Path(__file__).parent.parent
    shadow_exits_path = workspace_root / "logs" / "shadow_exits.csv"
    
    if not shadow_exits_path.exists():
        print(f"ERROR: {shadow_exits_path} not found!")
        return
    
    print_header("POLYOU BOT - WEEKLY STATUS CHECK")
    print(f"Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Data Source: {shadow_exits_path}")
    
    # Load all trades
    trades = load_trades(shadow_exits_path)
    
    if not trades:
        print("\nNo trades found in log file.")
        return
    
    # Calculate date range
    first_trade = min(trades, key=lambda t: t['ts'])
    last_trade = max(trades, key=lambda t: t['ts'])
    days_tracked = (last_trade['ts'] - first_trade['ts']).total_seconds() / 86400
    
    print(f"\nTracking Period:")
    print(f"  First Trade: {first_trade['ts'].strftime('%Y-%m-%d %H:%M')}")
    print(f"  Last Trade:  {last_trade['ts'].strftime('%Y-%m-%d %H:%M')}")
    print(f"  Duration:    {days_tracked:.1f} days")
    print(f"  Total Trades: {len(trades)}")
    
    # Overall performance
    total_pnl = sum(t['true_pnl'] for t in trades)
    total_wins = sum(1 for t in trades if t['true_pnl'] > 0)
    total_losses = sum(1 for t in trades if t['true_pnl'] < 0)
    win_rate = (total_wins / len(trades) * 100) if trades else 0
    daily_profit = total_pnl / days_tracked if days_tracked > 0 else 0
    
    print_header("OVERALL PERFORMANCE")
    print(f"Total P&L:       ${total_pnl:,.2f}")
    print(f"Daily Profit:    ${daily_profit:.2f}/day")
    print(f"Win Rate:        {win_rate:.1f}% ({total_wins}W / {total_losses}L)")
    print(f"Avg per Trade:   ${total_pnl/len(trades):.3f}")
    
    # Progress toward goal
    target_daily = 50.0
    current_pct = (daily_profit / target_daily * 100) if target_daily > 0 else 0
    gap = target_daily - daily_profit
    
    print(f"\nProgress toward ${target_daily:.0f}/day goal:")
    print(f"  Current: ${daily_profit:.2f}/day ({current_pct:.1f}% of target)")
    print(f"  Gap:     ${gap:.2f}/day ({gap/daily_profit:.1f}x improvement needed)")
    
    # Analyze leaders (all-time)
    leader_stats_all = analyze_leaders(trades)
    print_leader_table(leader_stats_all, top_n=15, title="All-Time Leader Performance")
    
    # Last 7 days
    if days_tracked >= 7:
        leader_stats_7d = analyze_leaders(trades, days_filter=7)
        print_leader_table(leader_stats_7d, top_n=10, title="Last 7 Days Performance")
    
    # Last 30 days (if we have that much data)
    if days_tracked >= 30:
        leader_stats_30d = analyze_leaders(trades, days_filter=30)
        print_leader_table(leader_stats_30d, top_n=10, title="Last 30 Days Performance")
    
    # Identify consistently profitable leaders
    print_header("PROFITABLE LEADERS (5+ Trades, Positive P&L)")
    profitable = {addr: stats for addr, stats in leader_stats_all.items() 
                  if stats['trades'] >= 5 and stats['total_pnl'] > 0}
    
    if profitable:
        print_leader_table(profitable, top_n=len(profitable), title="Qualified Profitable Leaders")
        print(f"\nFound {len(profitable)} consistently profitable leaders")
    else:
        print("\nNo leaders with 5+ trades and positive P&L")
    
    # Check activity of known good leaders
    known_good = ['0xa3d043b2', '0x5d3cc45e']
    print_header("KNOWN PROFITABLE LEADERS STATUS")
    
    for leader_prefix in known_good:
        matching = {addr: stats for addr, stats in leader_stats_all.items() 
                   if addr.startswith(leader_prefix)}
        
        if matching:
            for addr, stats in matching.items():
                last_trade_str = stats['last_trade'].strftime('%Y-%m-%d %H:%M') if stats['last_trade'] else "N/A"
                days_since = (datetime.now(stats['last_trade'].tzinfo) - stats['last_trade']).total_seconds() / 86400 if stats['last_trade'] else 999
                
                print(f"\nLeader {format_leader_address(addr)}:")
                print(f"  Total P&L:      ${stats['total_pnl']:.2f}")
                print(f"  Trades:         {stats['trades']}")
                print(f"  Win Rate:       {stats['wins']/stats['trades']*100:.1f}%")
                print(f"  Last Trade:     {last_trade_str} ({days_since:.1f} days ago)")
                
                if days_since > 3:
                    print(f"  ⚠️  WARNING: No activity in {days_since:.1f} days!")
        else:
            print(f"\n⚠️  Leader {leader_prefix}... NOT FOUND in recent data!")
    
    # Milestones
    print_header("DATA COLLECTION MILESTONES")
    
    if days_tracked < 30:
        days_to_30 = 30 - days_tracked
        print(f"📊 Currently at {days_tracked:.1f} days")
        print(f"   Need {days_to_30:.1f} more days to reach 30-day checkpoint")
        print(f"   Target: {(last_trade['ts'] + timedelta(days=days_to_30)).strftime('%Y-%m-%d')}")
    else:
        print(f"✅ 30-day checkpoint: REACHED ({days_tracked:.1f} days collected)")
    
    if days_tracked < 60:
        days_to_60 = 60 - days_tracked
        print(f"\n💰 60-day capital decision threshold:")
        print(f"   Need {days_to_60:.1f} more days")
        print(f"   Target: {(last_trade['ts'] + timedelta(days=days_to_60)).strftime('%Y-%m-%d')}")
    else:
        print(f"\n✅ 60-day threshold: REACHED - Consider capital deployment if performance sustained")
    
    # Recommendations
    print_header("RECOMMENDATIONS")
    
    if days_tracked < 30:
        print("🕐 Continue paper trading to collect more data")
        print("   Target: 30 days minimum before any capital decisions")
    elif days_tracked < 60:
        print("📈 Evaluate 30-day consistency")
        print("   Are the profitable leaders still performing?")
        print("   Any new consistent winners emerging?")
    else:
        print("🎯 60+ days collected - Time to evaluate capital deployment")
        if daily_profit >= 1.50:
            print(f"   Performance: ${daily_profit:.2f}/day is sustainable")
            print("   Consider starting with $1K-$2K test capital")
        else:
            print(f"   Performance: ${daily_profit:.2f}/day is below $1.50 threshold")
            print("   Recommend continuing paper trading or re-evaluating strategy")
    
    if len(profitable) < 3:
        print(f"\n⚠️  Only {len(profitable)} profitable leaders - limited diversification")
        print("   Risk is concentrated - be cautious with scaling")
    
    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    main()
