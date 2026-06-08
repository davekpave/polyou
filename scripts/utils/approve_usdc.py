import os
import time
from dotenv import load_dotenv
from web3 import Web3



def approve_usdc_for_polymarket():
    print("Checking your environment and wallet...")
    load_dotenv()
    private_key = os.getenv('POLY_PRIVATE_KEY')
    
    if not private_key:
        print("ERROR: POLY_PRIVATE_KEY not found in .env")
        return

    # Use working public Polygon RPCs
    rpc_urls = [
        'https://1rpc.io/matic',
        'https://polygon-bor-rpc.publicnode.com',
        'https://polygon.rpc.blxrbnd.com'
    ]
    w3 = None
    for url in rpc_urls:
        tmp = Web3(Web3.HTTPProvider(url))
        if tmp.is_connected():
            w3 = tmp
            break
            
    if not w3 or not w3.is_connected():
        print("ERROR: Could not connect to Polygon network.")
        return

    account = w3.eth.account.from_key(private_key)
    address = account.address
    print(f"Connected successfully. Your Wallet: {address}")

    # Checking MATIC (gas) balance
    matic_balance = w3.eth.get_balance(address)
    print(f"MATIC Balance: {w3.from_wei(matic_balance, 'ether')} MATIC")
    if matic_balance == 0:
        print("ERROR: You have exactly 0 MATIC. You need a small amount of MATIC to pay the blockchain gas fee for approval.")
        return

    # Addresses
    USDC_ADDRESS = w3.to_checksum_address('0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174')
    POLYMARKET_EXCHANGE = w3.to_checksum_address('0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E')
    
    # Tiny standard ERC20 ABI for balanceOf and approve
    erc20_abi = [
        {"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},
        {"constant":False,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"type":"function"},
        {"constant":True,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"type":"function"}
    ]

    usdc = w3.eth.contract(address=USDC_ADDRESS, abi=erc20_abi)

    # Check USDC balance
    usdc_balance = usdc.functions.balanceOf(address).call()
    print(f"USDC.e Balance: {usdc_balance / 1e6} USDC.e")
    if usdc_balance == 0:
        print("WARNING: You currently have 0 USDC.e. You will still need to fund this wallet with bridged USDC.e before the bot can trade.")

    # Check current allowance
    current_allowance = usdc.functions.allowance(address, POLYMARKET_EXCHANGE).call()
    if current_allowance > 0:
        print("Great news: You ALREADY have some allowance approved! Your bot should be able to trade if you have enough USDC.e balance.")
        # We don't exit here, we'll let them reset / max it out just in case.

    print("\nPreparing to send 'Approve USDC.e for Polymarket' transaction...")
    MAX_UINT256 = (2**256) - 1
    
    tx = usdc.functions.approve(POLYMARKET_EXCHANGE, MAX_UINT256).build_transaction({
        'from': address,
        'nonce': w3.eth.get_transaction_count(address),
        'gas': 100000,
        'maxFeePerGas': w3.to_wei(150, 'gwei'),
        'maxPriorityFeePerGas': w3.to_wei(60, 'gwei'),
    })

    print("Signing transaction...")
    signed_tx = w3.eth.account.sign_transaction(tx, private_key)

    print("Broadcasting transaction to Polygon...")
    try:
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        print(f"Transaction sent! Hash: {tx_hash.hex()}")
        print("Waiting for confirmation (this usually takes 5-15 seconds)...")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        
        if receipt.status == 1:
            print("\nSUCCESS! You have approved USDC.e for Polymarket.")
            print("Your bot is now authorized to place trades automatically.")
        else:
            print("\nFAILED: The transaction reverted. Check Polygonscan for details.")
            
    except Exception as e:
        print(f"An error occurred while sending the transaction: {e}")

if __name__ == "__main__":
    approve_usdc_for_polymarket()
