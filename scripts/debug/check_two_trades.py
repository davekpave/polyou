import requests

tokens = [
    "93752370469853593428275514344712256378857739183343977594575260876189010991162", # 9.2966
    "77890358925400134686674603962524827014747638427924246119593753323567249574474"  # 3.984
]

for t in tokens:
    r = requests.get(f"https://gamma-api.polymarket.com/events?clobTokenIds={t}")
    if r.status_code == 200:
        data = r.json()
        if data:
            slug = data[0].get('slug')
            closed = data[0].get('closed')
            market = data[0].get('markets', [{}])[0]
            
            p = market.get('outcomePrices', "[]")
            import json
            prices = json.loads(p) if isinstance(p, str) else p
            print(f"Token: {t[:10]}... => Market: {slug} | Closed: {closed} | Prices: {prices}")
