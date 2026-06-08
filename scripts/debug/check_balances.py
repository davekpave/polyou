import os
from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account

load_dotenv()
pk = os.getenv('POLY_PRIVATE_KEY')
account = Account.from_key(pk)
my_address = account.address

w3 = Web3(Web3.HTTPProvider('https://polygon.drpc.org'))

ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function"
    }
]

tokens = {
    "USDC.e (Bridged)": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
    "USDC (Native)": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
    "POL (MATIC)": "None"
}

print(f"Checking balances for EOA Address: {my_address}")
for name, address in tokens.items():
    if address == "None":
        bal = w3.eth.get_balance(my_address)
        print(f"{name}: {w3.from_wei(bal, 'ether')}")
    else:
        contract = w3.eth.contract(address=w3.to_checksum_address(address), abi=ERC20_ABI)
        bal = contract.functions.balanceOf(my_address).call()
        decimals = contract.functions.decimals().call()
        print(f"{name}: {bal / (10 ** decimals)}")

