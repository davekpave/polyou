#!/usr/bin/env python3
"""Check performance since bot restart."""
import csv
from datetime import datetime, timezone

# Bot restarted at 2026-05-11 16:13:23 UTC (12:13:23 ET)
RESTART_TIME = datetime(2026, 5, 11, 16, 13, 23, tzinfo=timezone.utc)

trades_since_restart = []
with open('logs/shadow_exits.csv', 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        exit_time = datetime.fromisoformat(row['ts_iso'].replace('Z', '+00:00'))
        if exit_time >= RESTART_TIME:
            trades_since_restart.append(row)

print(f"\n{'='*80}")
print(f"PERFORMANCE SINCE RESTART (2026-05-11 16:13:23 UTC)")
print(f"{'='*80}\n")

total_pnl = 0
wins = 0
losses = 0
stop_losses = 0
stop_loss_pnl = 0
expiry_wins = 0
expiry_win_pnl = 0
settled_zero = 0

for trade in trades_since_restart:
    pnl = float(trade['profit_per_share'])
    exit_type = trade['exit_type']
    total_pnl += pnl
    
    if pnl > 0:
        wins += 1
    else:
        losses += 1
    
    if exit_type == 'STOP_LOSS':
        stop_losses += 1
        stop_loss_pnl += pnl
    elif exit_type == 'EXPIRY_BID' and pnl > 0:
        expiry_wins += 1
        expiry_win_pnl += pnl
    elif exit_type == 'SETTLED_ZERO':
        settled_zero += 1

print(f"Total Trades: {len(trades_since_restart)}")
print(f"Wins: {wins} | Losses: {losses}")
print(f"Win Rate: {100*wins/len(trades_since_restart):.1f}%")
print(f"\nTotal P&L: {total_pnl:+.4f}")
print(f"Average P&L: {total_pnl/len(trades_since_restart):+.4f}")
print(f"\nStop-Losses Triggered: {stop_losses}")
print(f"Stop-Loss P&L: {stop_loss_pnl:.4f} (avg: {stop_loss_pnl/stop_losses if stop_losses > 0 else 0:.4f})")
print(f"\nExpiry Wins: {expiry_wins}")
print(f"Expiry Win P&L: {expiry_win_pnl:+.4f} (avg: {expiry_win_pnl/expiry_wins if expiry_wins > 0 else 0:+.4f})")
print(f"\nSettled Zero (old positions): {settled_zero}")

print(f"\n{'='*80}")
print("RECENT TRADES:")
print(f"{'='*80}\n")

for trade in trades_since_restart[-5:]:  # Last 5 trades
    print(f"{trade['ts_iso'][:19]} | {trade['symbol']:6} {trade['side']:4} | "
          f"Entry: {float(trade['entry_price']):5.3f} | {trade['exit_type']:12} | "
          f"P&L: {float(trade['profit_per_share']):+7.4f}")
