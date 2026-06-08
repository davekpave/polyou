import requests, json
url = "https://data.chain.link/graphql"
query = """query LIVE_STREAM_REPORTS_QUERY($feedId: String!) {
  liveStreamReports(feedId: $feedId, limit: 3) {
    nodes { validFromTimestamp price }
  }
}"""
variables = {"feedId": "0x00039d9e45394f473ab1f050a1b963e6b05351e52d71e507509ada0c95ed75b8"}
r = requests.post(url, json={"query": query, "variables": variables}, headers={"Content-Type":"application/json"})
r.raise_for_status()
print(json.dumps(r.json(), indent=2))
