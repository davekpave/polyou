import requests
from datetime import datetime
import warnings
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

# Target: 4:15 PM ET on April 23, 2026
# Timestamp = 4:15 AM + 12 hours
target_unix = 1776888900 + (12 * 3600)  # 1776932100

print('Fetching historical prices for April 23, 2026 at 4:15 PM ET')
print(f'Target timestamp: {target_unix}')
print()

# Try Kraken OHLC (1-minute candles)
print('=== KRAKEN Historical OHLC ===')
pairs = {'XBTUSD': 'BTC', 'ETHUSD': 'ETH'}

for kraken_pair, symbol in pairs.items():
    try:
        # Get OHLC data starting a bit before target
        r = requests.get('https://api.kraken.com/0/public/OHLC',
                        params={
                            'pair': kraken_pair, 
                            'interval': 1,  # 1-minute candles
                            'since': target_unix - 600  # Start 10 min before
                        },
                        timeout=10,
                        verify=False)
        
        if r.status_code == 200:
            data = r.json()
            if 'result' in data:
                for pair_key, ohlc_data in data['result'].items():
                    if isinstance(ohlc_data, list) and len(ohlc_data) > 0:
                        # Find candle at or closest to 4:15 AM
                        closest_candle = None
                        min_diff = float('inf')
                        
                        for candle in ohlc_data:
                            ts = candle[0]
                            diff = abs(ts - target_unix)
                            if diff < min_diff:
                                min_diff = diff
                                closest_candle = candle
                        
                        if closest_candle:
                            ts = closest_candle[0]
                            open_p = float(closest_candle[1])
                            high_p = float(closest_candle[2])
                            low_p = float(closest_candle[3])
                            close_p = float(closest_candle[4])
                            dt = datetime.fromtimestamp(ts)
                            
                            print(f'{symbol}USD:')
                            print(f'  Time: {dt.strftime("%Y-%m-%d %I:%M %p")} (within {min_diff}s of target)')
                            print(f'  Close: ${close_p:,.2f}')
                            print(f'  Open: ${open_p:,.2f}, High: ${high_p:,.2f}, Low: ${low_p:,.2f}')
                            print()
        else:
            print(f'{symbol}: HTTP {r.status_code}')
            
    except Exception as e:
        print(f'{symbol} Error: {e}')
        print()

print()
print('=== Alternative: Current prices from APIs ===')
print('(if historical data unavailable, showing current instead)')
print()

# Fallback to current prices if historical fails
try:
    r = requests.get('https://api.kraken.com/0/public/Ticker',
                    params={'pair': 'XBTUSD,ETHUSD'},
                    timeout=5,
                    verify=False)
    if r.status_code == 200:
        data = r.json()
        for pair, info in data.get('result', {}).items():
            symbol = 'BTC' if 'XBT' in pair or 'BTC' in pair else 'ETH'
            price = float(info['c'][0])
            print(f'{symbol}USD (current): ${price:,.2f}')
except Exception as e:
    print(f'Current price fetch error: {e}')
