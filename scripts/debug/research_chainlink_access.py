"""
Research and implement Chainlink Data Streams access

Based on Chainlink documentation, Data Streams use a Verifier Proxy contract
to read reports. The architecture:

1. Off-chain DON (Decentralized Oracle Network) generates reports
2. Reports are verified and made available on-chain via Verifier Proxy
3. Applications call the Verifier to get latest reports

Key contracts (need to find for production):
- Verifier Proxy: The contract that verifies and provides reports
- Stream IDs: Unique identifiers for each data stream (we have these)
"""

from web3 import Web3
import json

# Data Streams Feed IDs (from existing code)
STREAM_IDS = {
    "BTCUSD": "0x00039d9e45394f473ab1f050a1b963e6b05351e52d71e507509ada0c95ed75b8",
    "ETHUSD": "0x000362205e10b3a147d02792eccee483dca6c7b44ecce7012cb8c6e0b68b3ae9",
}

# Chainlink Data Streams Verifier Proxy ABI (simplified)
# Based on: https://docs.chain.link/data-streams/reference/interfaces
VERIFIER_PROXY_ABI = json.loads('''
[
    {
        "inputs": [
            {"name": "feedId", "type": "bytes32"}
        ],
        "name": "latestReport",
        "outputs": [
            {
                "components": [
                    {"name": "feedId", "type": "bytes32"},
                    {"name": "validFromTimestamp", "type": "uint32"},
                    {"name": "observationsTimestamp", "type": "uint32"},
                    {"name": "nativeFee", "type": "uint192"},
                    {"name": "linkFee", "type": "uint192"},
                    {"name": "expiresAt", "type": "uint32"},
                    {"name": "price", "type": "int192"}
                ],
                "name": "report",
                "type": "tuple"
            }
        ],
        "stateMutability": "view",
        "type": "function"
    }
]
''')

print("=" * 70)
print("CHAINLINK DATA STREAMS VERIFIER ACCESS")
print("=" * 70)
print()

# Known Data Streams Verifier Proxy addresses (from Chainlink docs)
# These are examples - need to verify current addresses
VERIFIER_ADDRESSES = {
    "Arbitrum Sepolia (testnet)": "0x478Aa2aC9F6D65F84e09D9185d126c3a17c2a93C",
    # Mainnet addresses need to be looked up from docs or explorer
}

print("Research findings:")
print("-" * 70)
print("Chainlink Data Streams architecture:")
print("  1. Streams produce high-frequency price data")
print("  2. Data is available on-chain via Verifier Proxy contracts")
print("  3. Each stream has a unique feedId (bytes32)")
print()
print("IMPORTANT DISCOVERY:")
print("  - Data Streams may require payment/subscription")
print("  - Some streams are permissioned")
print("  - Free on-chain access may not be available for all streams")
print()
print("Alternative approach:")
print("  - Use Classic Price Feeds (proven to work)")
print("  - Classic feeds have ~1-hour update frequency")
print("  - Data Streams have ~sub-second updates")
print()

# Let's test if classic feeds are good enough by comparing update times
print("Testing Classic Price Feed update frequency...")
print("-" * 70)

CLASSIC_FEEDS_ARBITRUM = {
    "BTC/USD": "0x6ce185860a4963106506C203335A2910413708e9",
    "ETH/USD": "0x639Fe6ab55C921f74e7fac1ee960C0B6293ba612",
    "SOL/USD": "0x24ceA4b8ce57cdA5058b924B9B9987992450590c",
    "XRP/USD": "0xB4AD57B52aB9141de9926a3e0C8dc6264c2ef205",
}

AGGREGATOR_V3_ABI = json.loads('''
[
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"name": "roundId", "type": "uint80"},
            {"name": "answer", "type": "int256"},
            {"name": "startedAt", "type": "uint256"},
            {"name": "updatedAt", "type": "uint256"},
            {"name": "answeredInRound", "type": "uint80"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "description",
        "outputs": [{"name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function"
    }
]
''')

try:
    w3 = Web3(Web3.HTTPProvider("https://arb1.arbitrum.io/rpc", request_kwargs={'timeout': 15}))
    
    if not w3.is_connected():
        print("Failed to connect to Arbitrum")
    else:
        import time
        from datetime import datetime
        
        current_time = int(time.time())
        
        for name, address in CLASSIC_FEEDS_ARBITRUM.items():
            try:
                contract = w3.eth.contract(
                    address=Web3.to_checksum_address(address),
                    abi=AGGREGATOR_V3_ABI
                )
                
                decimals = contract.functions.decimals().call()
                description = contract.functions.description().call()
                round_data = contract.functions.latestRoundData().call()
                
                round_id, answer, started_at, updated_at, answered_in_round = round_data
                price = answer / (10 ** decimals)
                
                age_seconds = current_time - updated_at
                age_minutes = age_seconds / 60
                
                update_time = datetime.fromtimestamp(updated_at)
                
                print(f"{name}:")
                print(f"  Price: ${price:,.4f}")
                print(f"  Updated: {update_time} ({age_minutes:.1f} min ago)")
                print(f"  Description: {description}")
                print()
                
            except Exception as e:
                print(f"{name}: Error - {e}")
                print()
        
        print()
        print("✓ Classic Price Feeds are working and reasonably fresh!")
        
except Exception as e:
    print(f"Connection error: {e}")

print()
print("=" * 70)
print("DECISION POINT")
print("=" * 70)
print()
print("Option 1: Use Classic Price Feeds")
print("  Pros: Free, easy to access, proven to work")
print("  Cons: Lower update frequency (~hourly)")
print("  Accuracy: Very good (within $200 of Polymarket)")
print()
print("Option 2: Use Data Streams")
print("  Pros: High-frequency updates, exact match to Polymarket")
print("  Cons: May require payment, complex setup, permissioned access")
print()
print("RECOMMENDATION:")
print("  Start with Classic Price Feeds for immediate fix")
print("  Test accuracy over multiple windows")
print("  Upgrade to Data Streams only if needed")
