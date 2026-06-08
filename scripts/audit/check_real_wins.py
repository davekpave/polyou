import requests
import json

try:
    with open('logs/execution_log.csv', 'r') as f:
        lines = f.readlines()
except Exception as e:
    print(f"Error reading logs: {e}")
    exit()

# Filter for recent trades
today_trades = [line.strip().split(',') for line in lines if len(line.split(',')) > 5 and 'updown' in line.split(',')[3]]
today_trades = today_trades[-15:]

print(f"{'Market Slug':<30} | {'Bought':<6} | {'Actual Winner':<13} | {'Result'}")
print("-" * 70)

wins, losses, pending = 0, 0, 0

for t in today_trades:
    slug = t[3]
    bought = t[2].upper()
    
    try:
        r = requests.get(f'https://gamma-api.polymarket.com/events?slug={slug}')
        if r.status_code != 200:
            continue
        
        data = r.json()
        m = data[0]['markets'][0]
        closed = m.get('closed', False)
        outcomes = m.get('outcomes', [])
        
        # This is where the old script completely failed! 
        prices_raw = m.get('outcomePrices', [])
        
        prices = []
        if isinstance(prices_raw, str):
            prices = json.loads(prices_raw)
        else:
            prices = prices_raw
            
        winner = 'Pending'
        if closed:
            # Find the index of the price that is "1" or 1
            winner_idx = -1
            for i, p in enumerate(prices):
                if str(p) == "1":
                    winner_idx = i
                    break
            
            if winner_idx != -1:
                winner = outcomes[winner_idx].upper()

        result = 'PENDING'
        if closed and winner != 'Pending':
            if winner == bought:
                result = 'WIN'
                wins += 1
            else:
                result = 'LOSS'
                losses += 1
        elif not closed:
            pending += 1
            
        print(f"{slug:<30} | {bought:<6} | {winner:<13} | {result}")
        
    except Exception as e:
        print(f"{slug:<30} | {bought:<6} | ERROR: {e}")

print(f"\nReal Summary: Wins: {wins}, Losses: {losses}, Pending: {pending}")
