import requests, json

url = 'https://atlas-postgraphile-timescale.public.o11y.prod.cldev.sh/graphql'

query = """query LIVE_STREAM_REPORTS_QUERY($feedId: String!) {
  liveStreamReports(feedId: $feedId, limit: 3) {
    nodes { validFromTimestamp price }
  }
}"""

payload = {
    'query': query,
    'variables': {'feedId': '0x00039d9e45394f473ab1f050a1b963e6b05351e52d71e507509ada0c95ed75b8'}
}

headers = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'Origin': 'https://data.chain.link',
    'Referer': 'https://data.chain.link/streams',
    'User-Agent': 'Mozilla/5.0',
}

print("--- POST atlas-postgraphile-timescale ---")
r = requests.post(url, json=payload, headers=headers, timeout=10)
print('Status:', r.status_code)
print(r.text[:2000])

# Also try the test/stage endpoint listed in the CSP
url2 = 'https://atlas-postgraphile-timescale-test.public.o11y.stage.cldev.sh/graphql'
print("\n--- POST atlas-postgraphile-timescale-test (stage) ---")
r2 = requests.post(url2, json=payload, headers=headers, timeout=10)
print('Status:', r2.status_code)
print(r2.text[:2000])

# Try main postgraphile (non-timescale)
url3 = 'https://atlas-postgraphile.public.main.prod.cldev.sh/graphql'
print("\n--- POST atlas-postgraphile main prod ---")
r3 = requests.post(url3, json=payload, headers=headers, timeout=10)
print('Status:', r3.status_code)
print(r3.text[:500])
