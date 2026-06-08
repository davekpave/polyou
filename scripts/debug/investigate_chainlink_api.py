import requests
import json

# The feed IDs from the old implementation
FEED_IDS = {
    "BTCUSD": "0x00039d9e45394f473ab1f050a1b963e6b05351e52d71e507509ada0c95ed75b8",
    "ETHUSD": "0x000362205e10b3a147d02792eccee483dca6c7b44ecce7012cb8c6e0b68b3ae9",
}

print("=" * 70)
print("INVESTIGATING CHAINLINK DATA STREAMS ACCESS")
print("=" * 70)
print()

# Test 1: Old GraphQL endpoint that was deprecated
print("Test 1: Old GraphQL endpoint (likely deprecated)")
print("-" * 70)
try:
    query = """
    query FeedLatestReport($feedId: String!) {
        report(where: {feedId: {_eq: $feedId}}, limit: 1, order_by: {block_timestamp_ns: desc}) {
            feedId
            answer
            block_timestamp_ns
        }
    }
    """
    r = requests.post(
        "https://data.chain.link/api/query-timescale",
        json={"query": query, "variables": {"feedId": FEED_IDS["BTCUSD"]}},
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=10
    )
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        print(f"Response: {r.json()}")
    else:
        print(f"Failed: {r.text[:200]}")
except Exception as e:
    print(f"Error: {e}")
print()

# Test 2: Try direct feed query (might be on-chain only now)
print("Test 2: Various API endpoint attempts")
print("-" * 70)

test_urls = [
    f"https://data.chain.link/api/feeds/{FEED_IDS['ETHUSD']}/latest",
    f"https://data.chain.link/api/v1/eth-usd/latest",
    "https://data.chain.link/api/streams/eth-usd",
]

for url in test_urls:
    try:
        r = requests.get(url, timeout=5)
        print(f"{url}")
        print(f"  Status: {r.status_code}")
        if r.status_code == 200 and 'json' in r.headers.get('content-type', ''):
            print(f"  JSON: {json.dumps(r.json(), indent=2)[:500]}")
        print()
    except Exception as e:
        print(f"{url}")
        print(f"  Error: {e}")
        print()

# Test 3: Check if the browser page loads JSON data asynchronously
print("Test 3: Looking for browser API calls (Network tab)")
print("-" * 70)
print("The data.chain.link/streams pages are React apps that may load data via API")
print("We need to find what API call the browser makes to get the latest price")
print()

# Try to find the API by looking at the page and intercepting network calls
print("Recommendation: Use browser DevTools Network tab on https://data.chain.link/streams/eth-usd")
print("to see what API endpoints are called for live price updates")
