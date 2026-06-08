"""
Quick script to manually close stuck position shares on Polymarket.
"""
import os
import sys
from py_clob_client.client import ClobClient
from eth_account import Account

# Token ID for BTCUSD DOWN from the screenshot
STUCK_TOKEN_ID = "10144773386207110825236225540601933558995705152609460665226496228092098187752"

def main():
    private_key = os.getenv("POLY_PRIVATE_KEY")
    if not private_key:
        print("ERROR: POLY_PRIVATE_KEY environment variable not set")
        return
    
    proxy_address = os.getenv("POLYMARKET_PROXY_ADDRESS")
    account = Account.from_key(private_key)
    funder = proxy_address if proxy_address else account.address
    signature_type = 2 if proxy_address else 0
    
    print(f"Initializing client for funder: {funder}")
    
    client = ClobClient(
        host="https://clob.polymarket.com",
        key=private_key,
        chain_id=137,
        funder=funder,
        signature_type=signature_type,
    )
    
    creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)
    
    print(f"\nChecking balance for token: {STUCK_TOKEN_ID}")
    
    # Get current balance
    try:
        balances = client.get_balances()
        token_balance = None
        
        for balance in balances:
            if balance.get("asset_id") == STUCK_TOKEN_ID:
                token_balance = float(balance.get("balance", 0))
                break
        
        if token_balance is None or token_balance == 0:
            print("No shares found for this token. Already closed?")
            return
        
        print(f"Found {token_balance} shares")
        
        # Place market sell order to dump at any price
        print(f"\nPlacing SELL order for {token_balance} shares...")
        print("Using price 0.01 (1 cent) to guarantee fill")
        
        order_args = {
            "market": STUCK_TOKEN_ID,
            "side": "SELL",
            "price": 0.01,  # Dump at 1 cent to guarantee fill
            "size": token_balance,
            "order_type": "GTC",
        }
        
        response = client.post_order(order_args)
        print(f"\nOrder placed: {response}")
        
        order_id = response.get("orderID") or response.get("id")
        status = response.get("status") or response.get("state")
        
        print(f"Order ID: {order_id}")
        print(f"Status: {status}")
        
        if status in ("filled", "matched"):
            print("\n✅ Order filled immediately! Stuck shares closed.")
        elif status in ("open", "live"):
            print("\n⏳ Order resting on book. Should fill soon at 1¢...")
            print(f"Check status: https://polymarket.com or run get_order({order_id})")
        else:
            print(f"\n⚠️ Unexpected status: {status}")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
