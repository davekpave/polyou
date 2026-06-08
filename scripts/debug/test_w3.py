import os, requests
from dotenv import load_dotenv
load_dotenv()
url = 'https://polygon-rpc.com'
hdrs = {'User-Agent': 'Mozilla/5.0'}
data = {'jsonrpc':'2.0','method':'eth_call','params':[{'to': '0x4D97DCd97eC945f40cF65F87097ACe5EA0476045', 'data': '0x00fdd58e0000000000000000000000001b78f77e168f24835f97a380198592a4e1210c1a0000000000000000000000000000000000000000000000000000000000000000'}, 'latest'],'id':1}
res = requests.post(url, headers=hdrs, json=data)
print(res.text)

