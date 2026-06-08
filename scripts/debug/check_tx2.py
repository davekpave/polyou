import requests

from web3 import Web3
w3 = Web3(Web3.HTTPProvider('https://polygon.drpc.org'))

# USDC.e
token = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
eoa = "0x000000000000000000000000415c6ea0f432fe64477d83355595f36ca385e68f"
payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "eth_getLogs",
    "params": [{
        "address": token,
        "fromBlock": "0x412E000",
        "toBlock": "latest",
        "topics": [
            "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef", # Transfer(address,address,uint256)
            eoa, # from EOA
            None
        ]
    }]
}

r = requests.post('https://polygon.drpc.org', json=payload).json()
logs = r.get('result', [])
print(f"Found {len(logs)} USDC.e outgoing transfers:")
for log in logs:
    to = "0x" + log['topics'][2][26:]
    val = int(log['data'], 16) / 1e6
    print(f"To: {to} | Value: {val}")

