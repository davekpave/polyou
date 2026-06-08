import requests, json
res = requests.get("https://clob.polymarket.com/markets?limit=10&active=true&closed=false").json()
for m in res['data']: 
  if m['accepting_orders']:
    print(m['tokens'][1]['token_id'])
    break

