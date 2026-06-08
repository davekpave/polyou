import os
import json
import requests
from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account

load_dotenv()
pk = os.getenv('POLY_PRIVATE_KEY')
account = Account.from_key(pk)
my_address = account.address

w3 = Web3(Web3.HTTPProvider('https://polygon.drpc.org'))

COLLATERAL_TOKEN = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174" 
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097EFe56114bCb37"

CTF_ABI = [
    {
        "type": "function",
        "name": "redeemPositions",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "collateralToken", "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "indexSets", "type": "uint256[]"}
        ],
        "outputs": []
    }
]

ctf_contract = w3.eth.contract(address=w3.to_checksum_address(CTF_ADDRESS), abi=CTF_ABI)

slugs = ["btc-updown-15m-1776144600", "btc-updown-15m-1776146400", "btc-updown-15m-1776148200", "btc-updown-15m-1776155400", "btc-updown-15m-1776156300"]

for slug in slugs:
    print(f"Checking market: {slug}")
    r = requests.get(f"https://gamma-api.polymarket.com/events?slug={slug}")
    if r.status_code == 200:
        markets = r.json()[0].get('markets', [])
        if not markets: continue
        condition_id = markets[0].get('conditionId')
        if not markets[0].get('closed'): continue
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
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction) # fixed rawTransaction to raw_transaction for v6
            print(f"Redeem Transaction Sent! Hash: {w3.to_hex(tx_hash)}")
            
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
            print(f"Redeem completed! Status: {receipt.status}")
        except Exception as e:
            if 'execution reverted' in str(e).lower() or 'zero' in str(e).lower() or "not enough" in str(e).lower() or 'none' in str(e).lower():
                 print(f"No win to redeem (or you lost/already redeemed): {slug}")
            else:
                 print(f"Error on {slug}: {e}")

