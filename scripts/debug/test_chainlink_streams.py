import requests
import json
import re

def fetch_chainlink_stream_price(symbol):
    """Fetch current price from Chainlink Data Streams web page"""
    urls = {
        'BTC': 'https://data.chain.link/streams/btc-usd',
        'ETH': 'https://data.chain.link/streams/eth-usd'
    }
    
    if symbol not in urls:
        print(f"Unknown symbol: {symbol}")
        return None
    
    url = urls[symbol]
    print(f"Fetching {symbol} from Chainlink Data Streams...")
    
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            print(f"Status {r.status_code}")
            return None
        
        html = r.text
        
        # Look for JSON data embedded in the page (Next.js often embeds data in __NEXT_DATA__)
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                print("Found __NEXT_DATA__, exploring structure...")
                
                # Navigate the structure to find price data
                # This will vary based on Chainlink's page structure
                def find_price(obj, path=""):
                    if isinstance(obj, dict):
                        for key, value in obj.items():
                            if key in ['price', 'answer', 'value', 'latestAnswer']:
                                print(f"Found potential price at {path}.{key}: {value}")
                            find_price(value, f"{path}.{key}")
                    elif isinstance(obj, list):
                        for i, item in enumerate(obj):
                            find_price(item, f"{path}[{i}]")
                
                find_price(data)
                
            except json.JSONDecodeError as e:
                print(f"Could not parse __NEXT_DATA__: {e}")
        
        # Also try to find price in plain HTML/text
        # Look for patterns like "78,764.81" or "2,400.08"
        price_patterns = [
            r'"answer"[:\s]+([0-9,]+\.?[0-9]*)',
            r'"price"[:\s]+([0-9,]+\.?[0-9]*)',
            r'latest[^0-9]+([0-9,]+\.?[0-9]*)',
        ]
        
        for pattern in price_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                print(f"Pattern '{pattern}' found: {matches[:5]}")  # First 5 matches
        
        return None
        
    except Exception as e:
        print(f"Error: {e}")
        return None

print("=" * 60)
print("Testing Chainlink Data Streams Price Extraction")
print("=" * 60)
print()

for symbol in ['BTC', 'ETH']:
    fetch_chainlink_stream_price(symbol)
    print()
    print("-" * 60)
    print()
