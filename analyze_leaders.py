"""
Analyze performance by leader address.

Reads logs/shadow_exits.csv and groups by leader_address to show:
- Total trades per leader
- Win rate
- Total P&L
- Average win/loss size
- Risk/reward ratio
"""

import csv
from collections import defaultdict
from datetime import datetime, timezone

# Filter for trades since latest bot restart
RESTART_TIME = datetime(2026, 5, 11, 16, 13, 23, tzinfo=timezone.utc)

CSV_PATH = "logs/shadow_exits.csv"

def main():
    # Track stats per leader
    leader_stats = defaultdict(lambda: {
        "trades": 0,
        "wins": 0,
        "stop_losses": 0,
        "total_pnl": 0.0,
        "win_sum": 0.0,
        "loss_sum": 0.0,
        "win_count": 0,
        "loss_count": 0,
    })
    
    total_trades = 0
    
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Filter by restart time
            ts_str = row.get("ts_iso", "")
            if ts_str:
                ts = datetime.fromisoformat(ts_str)
                if ts < RESTART_TIME:
                    continue
            
            leader = row.get("leader_address", "").strip()
            if not leader:
                # Old trades without leader tracking
                continue
            
            # Filter out invalid addresses (token_ids from old data)
            # Valid Ethereum address: 0x + 40 hex characters
            if not (leader.startswith("0x") and len(leader) == 42 and 
                    all(c in "0123456789abcdefABCDEF" for c in leader[2:])):
                continue
            
            total_trades += 1
            
            try:
                pnl = float(row.get("profit_per_share", 0))
            except (ValueError, TypeError):
                pnl = 0.0
            
            exit_type = row.get("exit_type", "")
            
            stats = leader_stats[leader]
            stats["trades"] += 1
            stats["total_pnl"] += pnl
            
            if exit_type == "STOP_LOSS":
                stats["stop_losses"] += 1
                stats["loss_sum"] += pnl
                stats["loss_count"] += 1
            elif pnl > 0:
                stats["wins"] += 1
                stats["win_sum"] += pnl
                stats["win_count"] += 1
            else:
                stats["loss_sum"] += pnl
                stats["loss_count"] += 1
    
    if total_trades == 0:
        print("No trades found with leader tracking since restart.")
        print(f"(Restart time: {RESTART_TIME.strftime('%Y-%m-%d %H:%M:%S %Z')})")
        print("\nNote: Leader tracking was just added. Restart bot to start collecting data.")
        return
    
    # Calculate derived metrics and sort by P&L
    leader_results = []
    for leader, stats in leader_stats.items():
        trades = stats["trades"]
        wins = stats["wins"]
        losses = trades - wins
        win_rate = (wins / trades * 100) if trades > 0 else 0
        
        avg_win = stats["win_sum"] / stats["win_count"] if stats["win_count"] > 0 else 0
        avg_loss = stats["loss_sum"] / stats["loss_count"] if stats["loss_count"] > 0 else 0
        rr_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        
        leader_results.append({
            "leader": leader[:10],  # Show first 10 chars
            "full_leader": leader,
            "trades": trades,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "stop_losses": stats["stop_losses"],
            "total_pnl": stats["total_pnl"],
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "rr_ratio": rr_ratio,
        })
    
    # Sort by total P&L descending
    leader_results.sort(key=lambda x: x["total_pnl"], reverse=True)
    
    print("=" * 90)
    print(f"LEADER PERFORMANCE ANALYSIS (since {RESTART_TIME.strftime('%Y-%m-%d %H:%M:%S %Z')})")
    print("=" * 90)
    print(f"\nTotal trades analyzed: {total_trades}")
    print(f"Leaders tracked: {len(leader_results)}")
    print()
    
    # Full ranking table
    print(f"{'Rank':<5} {'Leader':<45} {'Trades':>7} {'Win%':>6} {'Stops':>6} {'P&L':>8} {'AvgWin':>8} {'AvgLoss':>9} {'R:R':>6}")
    print("-" * 120)
    
    for i, result in enumerate(leader_results, 1):
        print(
            f"{i:<5} "
            f"{result['full_leader']:<45} "
            f"{result['trades']:>7} "
            f"{result['win_rate']:>5.1f}% "
            f"{result['stop_losses']:>6} "
            f"{result['total_pnl']:>+7.2f} "
            f"{result['avg_win']:>+7.2f} "
            f"{result['avg_loss']:>+8.2f} "
            f"{result['rr_ratio']:>5.2f}:1"
        )
    
    print()
    print("=" * 120)

if __name__ == "__main__":
    main()
