import requests
import json
with open('logs/execution_log.csv', 'r') as f:
    lines = f.readlines()

today_trades = [line.strip().split(',') for line in lines if len(line.split(',')) > 5 and 'updown' in line.split(',')[3] and float(line.split(',')[0]) > 1776100000]

print(f"Today\'s Trades: {len(today_trades)}\n{'Slug':<30} | {'Bought':<6} | {'Status':<10} | {'Result'}")
print('-'*80)
wins, losses, pending = 0, 0, 0

for t in today_trades[-15:]:
    slug = t[3]
    bought = t[2].upper()
    r = requests.get(f'https://gamma-api.polymarket.com/events?slug={slug}')
    try:
        m = r.json()[0]['markets'][0]
    except Exception:
        continue
        
    closed = m.get('closed', False)
    outcomes = m.get('outcomes', [])
    prices = m.get('outcomePrices', [])
    
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except json.JSONDecodeError:
            pass
            
    winning_side = 'N/A'
    if closed:
        for i, price in enumerate(prices):
            if str(price) == '1':
                winning_side = outcomes[i].upper()
    
    status = 'Closed' if closed else 'Open'
    outcome = 'PENDING'
    if closed:
        if winning_side == bought:
            outcome = 'WIN '
            wins += 1
        elif 'N/A' not in winning_side:
            outcome = 'LOSS'
            losses += 1
    else:
        pending += 1
        
    print(f"{slug:<30} | {bought:<6} | {status:<10} | {outcome} (Won: {winning_side})")

print(f'\nWins: {wins}, Losses: {losses}, Pending: {pending}')
