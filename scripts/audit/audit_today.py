import requests

try:
    with open('logs/execution_log.csv', 'r') as f:
        lines = f.readlines()
except Exception as e:
    print(f"Error reading logs: {e}")
    exit()

today_trades = []
for line in lines:
    parts = line.strip().split(',')
    if len(parts) > 5 and "updown" in parts[3] and float(parts[0]) > 1776100000:
        today_trades.append({
            'asset': parts[1],
            'side': parts[2].upper(),
            'slug': parts[3],
            'price': float(parts[4]),
            'size': float(parts[5])
        })

print(f"Found {len(today_trades)} trades today. Fetching resolutions...\n")
print(f"{'Market Slug':<30} | {'Bought':<6} | {'Status':<8} | {'Result'}")
print("-" * 65)

wins, losses, pending = 0, 0, 0

# Test the last 20 trades
for t in today_trades[-20:]:
    r = requests.get(f"https://gamma-api.polymarket.com/events?slug={t['slug']}")
    if r.status_code != 200: continue
    data = r.json()
    if not data: continue
    markets = data[0].get('markets', [])
    if not markets: continue
    
    m = markets[0]
    closed = m.get('closed', False)
    
    # Token 0 is usually UP(Yes), Token 1 is DOWN(No)
    tokens = m.get('tokens', [])
    winning_side = "N/A"
    if closed:
        if len(tokens) >= 2:
            if tokens[0].get('winner'):
                winning_side = "UP"
            elif tokens[1].get('winner'):
                winning_side = "DOWN"
    
    status = "Closed" if closed else "Open"
    outcome = "PENDING"
    if closed:
        if winning_side == t['side']:
            outcome = "WIN"
            wins += 1
        elif winning_side != "N/A":
            outcome = "LOSS"
            losses += 1
    else:
        pending += 1
        
    print(f"{t['slug']:<30} | {t['side']:<6} | {status:<8} | {outcome} (Won: {winning_side})")

print(f"\nSummary (last 20): Wins: {wins}, Losses: {losses}, Pending: {pending}")
