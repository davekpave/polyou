from dotenv import load_dotenv
load_dotenv()
import urllib.request as r, json
req = r.Request('https://clob.polymarket.com/orders?market=38438147258954153838398053844164240828786167822502850200902530144246798646345&closed=true', headers={'User-Agent': 'Mozilla/5.0'})
print(r.urlopen(req).read()[:500])

