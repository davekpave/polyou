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

print(f"{'Market Slug':<30} | {'Bought':<6} | {'Price':<6} | {'Outcomes':<20} | {'Status':<10} | {'Result'}")
print("-" * 90)

wins, losses, pending = 0, 0, 0

for t in today_trades[-15:]:
    r = requests.get(f"https://gamma-api.polymarket.com/events?slug={t['slug']}")
    if r.status_code != 200: continue
    data = r.json()
    if not data: continue
    markets = data[0].get('markets', [])
    if not markets: continue
    
    m = markets[0]
    closed = m.get('closed', False)
    
    outcomes = m.get('outcomes', [])
    prices = m.get('outcomePrices', [])
    
    winning_side = "N/A"
    
    if closed:
        for i, price in enumerate(prices):
            if price == "1":
                winning_side = outcomes[i].upper()
                
    status = "Closed" if closed else "Open"
    outcome = "PENDING"
    
    if closed:
        if winning_side == t['side'].upper():
            outcome = "WIN"
            wins += 1
        elif winning_side != "N/A":
            outcome = "LOSS"
            losses += 1
    else:
        pending += 1
        
    price_str = f""
    price_arr = ", ".join(prices)
    print(f"{t['slug']:<30} | {t['side']:<6} | {price_str:<6} | {price_arr:<20} | {status:<10} | {outcome} (Won: {winning_side})")

print(f"\nSummary (last 15): Wins: {wins}, Losses: {losses}, Pending: {pending}")

