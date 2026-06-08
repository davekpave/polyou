import csv
from collections import defaultdict

rows = list(csv.DictReader(open('logs/exit_log.csv')))

seen = set()
unique = []
for r in rows:
    key = (r['token_id'], r['type'])
    if key not in seen:
        seen.add(key)
        unique.append(r)

wins = [r for r in unique if r['type'] == 'TAKE_PROFIT']
losses = [r for r in unique if r['type'] in ('STOP_LOSS', 'TIME_DECAY')]

win_profits = [float(r['profit_cents']) for r in wins]
loss_profits = [float(r['profit_cents']) for r in losses]

entry_prices = [float(r['entry_price']) for r in unique]
avg_entry = sum(entry_prices) / len(entry_prices) if entry_prices else 0

print(f'Total unique positions: {len(unique)}')
print(f'Wins: {len(wins)}')
print(f'Losses: {len(losses)}')
print(f'Win rate: {len(wins)/len(unique)*100:.1f}%')
print(f'Avg entry price: {avg_entry:.3f}')
if win_profits:
    print(f'Avg win per share: {sum(win_profits)/len(win_profits):.4f}')
else:
    print('No wins')
if loss_profits:
    print(f'Avg loss per share: {sum(loss_profits)/len(loss_profits):.4f}')
else:
    print('No losses')
print()

def shares(entry, notional=5.0):
    buy_price = min(0.70, entry + 0.01)
    return int((notional * 0.98 / buy_price) * 100) / 100.0

total_pnl = 0
for r in wins:
    e = float(r['entry_price'])
    s = shares(e)
    pnl = float(r['profit_cents']) * s
    total_pnl += pnl

for r in losses:
    e = float(r['entry_price'])
    s = shares(e)
    pnl = float(r['profit_cents']) * s
    total_pnl += pnl

print(f'Estimated total P&L (all positions, 5 notional): ${total_pnl:.2f}')

entry = 0.60
s = shares(entry)
win_per_trade = (0.95 - entry) * s
loss_per_trade = (entry - 0.25 - entry) * s
print()
print(f'--- Per-trade math at entry=0.60 ---')
print(f'Shares bought at 5 notional: {s}')
print(f'Win (exit 0.95): +${win_per_trade:.2f}')
print(f'Loss (stop -0.25/share, exit ~0.35): -${abs(loss_per_trade):.2f}')
print(f'Break-even win rate: {abs(loss_per_trade)/(win_per_trade+abs(loss_per_trade))*100:.1f}%')
print()

for wr in [0.50, 0.55, 0.60, 0.65, 0.70]:
    ev = wr * win_per_trade - (1-wr) * abs(loss_per_trade)
    print(f'  Win rate {int(wr*100)}%: EV/trade=${ev:.2f}  |  5 trades/day=${ev*5:.2f}  |  10 trades/day=${ev*10:.2f}')

print()
print('--- Stake required for $48/day ---')
for trades in [5, 8, 10]:
    for wr in [0.60, 0.65]:
        ev_at_5 = wr * win_per_trade - (1-wr) * abs(loss_per_trade)
        needed_ev = 48 / trades
        multiplier = needed_ev / ev_at_5 if ev_at_5 > 0 else float('inf')
        stake_needed = 5.0 * multiplier
        print(f'  {trades} trades/day @ {int(wr*100)}% win rate -> need ${stake_needed:.0f}/trade')
