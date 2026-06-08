import os, sys, requests
from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account

load_dotenv()
pk = os.getenv('POLY_PRIVATE_KEY')
if not pk: sys.exit(0)
account = Account.from_key(pk)
my_address = account.address

w3 = Web3(Web3.HTTPProvider('https://polygon.drpc.org'))
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097EFe56114bCb37"
CTF_ABI = [{"type": "function", "name": "balanceOf", "stateMutability": "view", "inputs": [{"name": "account", "type": "address"}, {"name": "id", "type": "uint256"}], "outputs": [{"name": "", "type": "uint256"}]}]
ctf_contract = w3.eth.contract(address=w3.to_checksum_address(CTF_ADDRESS), abi=CTF_ABI)

# Process only today's trades from log
today_slugs = []
with open('logs/execution_log.csv', 'r') as f:
    for line in f:
        parts = line.strip().split(',')
        if len(parts) > 3 and "updown" in parts[3] and float(parts[0]) > 1776100000:
            today_slugs.append((parts[1], parts[2], parts[3]))

print(f"Checking exact token balances for the {len(today_slugs)} markets traded today...")

for asset, side, slug in today_slugs[-5:]:
    r = requests.get(f"https://gamma-api.polymarket.com/events?slug={slug}")
    if r.status_code != 200: continue
    markets = r.json()[0].get('markets', [])
    if not markets: continue
    market = markets[0]
    condition_id = market.get('conditionId')
    
    # Tokens identifiers: index 1 and 2
    # But to get the actual tokenID we need to hash it.
    # Polymarket API usually provides the token IDs!
    tokens = market.get('clobTokenIds', [])
    if not tokens:
        tokens = [market.get('tokens', [{}])[0].get('token_id', '0'), market.get('tokens', [{}])[1].get('token_id', '0')]
    
    if len(tokens) == 2:
        bal_up = ctf_contract.functions.balanceOf(my_address, int(tokens[0])).call()
        bal_down = ctf_contract.functions.balanceOf(my_address, int(tokens[1])).call()
        print(f"{slug} ({asset} {side}) => UP Shares: {bal_up/1e6}, DOWN Shares: {bal_down/1e6} | Closed: {market.get('closed')}")
