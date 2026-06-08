import csv

# Read exit log
with open('logs/exit_log.csv', 'r') as f:
    reader = csv.DictReader(f)
    trades = list(reader)

# Filter out the stuck positions from allowance bug (all at 0.6 -> 0.01)
real_trades = [t for t in trades if float(t['exit_price']) > 0.05]

print(f'Total real trades: {len(real_trades)}\n')

wins = [t for t in real_trades if float(t['profit_cents']) > 0]
losses = [t for t in real_trades if float(t['profit_cents']) <= 0]

print(f'Winners: {len(wins)}')
print(f'Losers: {len(losses)}')
print(f'Win Rate: {len(wins)/len(real_trades)*100:.1f}%\n')

if wins:
    avg_win = sum(float(t['profit_cents']) for t in wins) / len(wins)
    print(f'Average Win: ${avg_win:.3f}')

if losses:
    avg_loss = sum(float(t['profit_cents']) for t in losses) / len(losses)
    print(f'Average Loss: ${avg_loss:.3f}')

if wins and losses:
    ratio = abs(avg_win / avg_loss)
    print(f'\nProfit Factor: {ratio:.2f}x')
    print(f'Average loser is {1/ratio:.2f}x bigger than average winner')
    print(f'Need {abs(avg_loss / avg_win):.1f}x more winners than losers to break even')
