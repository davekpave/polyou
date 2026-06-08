import requests
import json

slug = "btc-updown-4h-1772557200"

resp = requests.get(
    "https://gamma-api.polymarket.com/events",
    params={"slug": slug},
    timeout=10,
)

print("Status:", resp.status_code)
print()
print(json.dumps(resp.json(), indent=2))
