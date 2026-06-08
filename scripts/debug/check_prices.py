import requests
from datetime import datetime

print('Fetching current prices...')
print()

# Fetch Kraken prices
print('=== KRAKEN ===')
try:
    r = requests.get('https://api.kraken.com/0/public/Ticker', 
                     params={'pair': 'BTCUSD,ETHUSD'}, 
                     timeout=5, 
                     verify=False)
    if r.status_code == 200:
        data = r.json()
        for pair, result in data.get('result', {}).items():
            symbol = 'BTC' if 'XBT' in pair or 'BTC' in pair else 'ETH'
            price = float(result['c'][0])
            print(f'{symbol}USD: ${price:,.2f}')
except Exception as e:
    print(f'Error: {e}')

print()

# Fetch CoinGecko prices  
print('=== COINGECKO ===')
try:
    r = requests.get('https://api.coingecko.com/api/v3/simple/price',
                     params={'ids': 'bitcoin,ethereum', 'vs_currencies': 'usd'},
                     timeout=5)
    if r.status_code == 200:
        data = r.json()
        btc = data.get('bitcoin', {}).get('usd')
        eth = data.get('ethereum', {}).get('usd')
        if btc:
            print(f'BTCUSD: ${btc:,.2f}')
        if eth:
            print(f'ETHUSD: ${eth:,.2f}')
except Exception as e:
    print(f'Error: {e}')
