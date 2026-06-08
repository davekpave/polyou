import os
import requests
from dotenv import load_dotenv

load_dotenv()
address = "0x415C6EA0F432fE64477d83355595f36Ca385E68f".lower()

# Instead of complex log parsing, we can just use the Polymarket Gamma API or a Block Explorer API
# But Polygon DRPC provides eth_getLogs. Let's get the token transfers TO this address.
RPC_URL = "https://polygon.drpc.org"

# TransferSingle(address operator, address from, address to, uint256 id, uint256 value)
# topic0: 0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62
# topic3: padding + address (to)

payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "eth_getLogs",
    "params": [{
        "address": "0x4D97DCd97eC945f40cF65F87097EFe56114bCb37",
        "fromBlock": "0x412E000", # recent block approx
        "toBlock": "latest",
        "topics": [
            "0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62",
            None,
            None,
            "0x000000000000000000000000415c6ea0f432fe64477d83355595f36ca385e68f"
        ]
    }]
}

r = requests.post(RPC_URL, json=payload)
logs = r.json().get('result', [])
print(f"Found {len(logs)} TransferSingle logs to this EOA on CTF.")

token_ids = set()
for log in logs:
    data = log.get('data', '0x')
    # data is non-indexed params: id (uint256), value (uint256)
    if len(data) >= 130:
        token_id_hex = data[0:66]
        token_ids.add(int(token_id_hex, 16))

print(f"Found {len(token_ids)} unique CTF tokens received.")

from web3 import Web3
w3 = Web3(Web3.HTTPProvider(RPC_URL))
ctf = w3.eth.contract(
    address=w3.to_checksum_address('0x4D97DCd97eC945f40cF65F87097EFe56114bCb37'),
    abi=[{'type':'function', 'name':'balanceOf', 'stateMutability':'view', 'inputs':[{'name':'account','type':'address'},{'name':'id','type':'uint256'}], 'outputs':[{'name':'','type':'uint256'}]}]
)

my_address = w3.to_checksum_address(address)
total_value = 0
for tid in token_ids:
    bal = ctf.functions.balanceOf(my_address, tid).call()
    shares = bal / 1e6
    if shares > 0:
        print(f"Token ID: {tid} -> Balance: {shares} shares")
        total_value += shares

if total_value == 0:
    print("The EOA currently holds NO active Polymarket shares.")
