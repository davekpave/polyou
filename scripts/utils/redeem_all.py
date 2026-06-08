import os
import requests
from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account

load_dotenv()
pk = os.getenv('POLY_PRIVATE_KEY')
account = Account.from_key(pk)
my_address = account.address

w3 = Web3(Web3.HTTPProvider('https://polygon.drpc.org'))
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097EFe56114bCb37"
COLLATERAL_TOKEN = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174" 

CTF_ABI = [{
    "type": "function", "name": "redeemPositions", "stateMutability": "nonpayable",
    "inputs": [
        {"name": "collateralToken", "type": "address"},
        {"name": "parentCollectionId", "type": "bytes32"},
        {"name": "conditionId", "type": "bytes32"},
        {"name": "indexSets", "type": "uint256[]"}
    ],
    "outputs": []
}]
ctf_contract = w3.eth.contract(address=w3.to_checksum_address(CTF_ADDRESS), abi=CTF_ABI)

# Read execution log
slugs = set()
with open('logs/execution_log.csv', 'r') as f:
    for line in f:
        parts = line.strip().split(',')
        if len(parts) > 3 and "updown" in parts[3]:
            slugs.add(parts[3])

print(f"Found {len(slugs)} unique markets to check for redemption...")

success_count = 0
for slug in list(slugs):
    # Get conditionId from gamma api
    r = requests.get(f"https://gamma-api.polymarket.com/events?slug={slug}")
    if r.status_code != 200: continue
    
    data = r.json()
    if not data: continue
    markets = data[0].get('markets', [])
    if not markets: continue
    
    market = markets[0]
    if not market.get('closed'): continue # Can only redeem closed markets
    
    condition_id = market.get('conditionId')
    if not condition_id: continue
    
    try:
        tx = ctf_contract.functions.redeemPositions(
            w3.to_checksum_address(COLLATERAL_TOKEN),
            w3.to_bytes(hexstr="0x0000000000000000000000000000000000000000000000000000000000000000"),
            w3.to_bytes(hexstr=condition_id),
            [1, 2]
        ).build_transaction({
            'from': my_address,
            'nonce': w3.eth.get_transaction_count(my_address),
            'gas': 200000,
            'gasPrice': w3.eth.gas_price,
        })
        signed_tx = w3.eth.account.sign_transaction(tx, private_key=pk)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        # We don't know if they won or lost from the receipt alone without parsing events, 
        # so we will just try all closed markets.
        success_count += 1
        print(f"Redeemed: {slug}")
    except Exception as e:
        # Fails if it reverts (like no tokens to redeem or condition not resolved)
        pass

print(f"Finished. Successfully broadcast redemption txs for {success_count} markets.")
