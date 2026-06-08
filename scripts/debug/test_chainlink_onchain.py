"""
Test script to explore Chainlink Data Streams on-chain access
"""

from web3 import Web3
import json

# Chainlink Data Streams feed IDs (from existing code)
FEED_IDS = {
    "BTCUSD": "0x00039d9e45394f473ab1f050a1b963e6b05351e52d71e507509ada0c95ed75b8",
    "ETHUSD": "0x000362205e10b3a147d02792eccee483dca6c7b44ecce7012cb8c6e0b68b3ae9",
    "SOLUSD": "0x0003b778d3f6b2ac4991302b89cb313f99a42467d6c9c5f96f57c29c0d2bc24f",
    "XRPUSD": "0x0003c16c6aed42294f5cb4741f6e59ba2d728f0eae2eb9e6d3f555808c59fc45",
}

print("=" * 70)
print("CHAINLINK DATA STREAMS ON-CHAIN ACCESS TEST")
print("=" * 70)
print()

# Chainlink Data Streams are available on multiple networks
# Polymarket likely uses Arbitrum or Base for low-cost access

# Test networks (public RPC endpoints)
networks = {
    "Arbitrum One": "https://arb1.arbitrum.io/rpc",
    "Base": "https://mainnet.base.org",
    "Polygon": "https://polygon-rpc.com",
}

print("Testing RPC connectivity...")
print("-" * 70)
for name, rpc_url in networks.items():
    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 10}))
        if w3.is_connected():
            latest_block = w3.eth.block_number
            print(f"✓ {name}: Connected, latest block {latest_block}")
        else:
            print(f"✗ {name}: Failed to connect")
    except Exception as e:
        print(f"✗ {name}: Error - {e}")
print()

# Chainlink Data Streams use a Verifier contract
# The contract address varies by network
# Common Chainlink Verifier addresses (example, need to find actual ones):

# For Arbitrum One, Chainlink Data Streams verifier (need to lookup actual address)
# Documentation: https://docs.chain.link/data-streams

print("Research Notes:")
print("-" * 70)
print("Chainlink Data Streams changed architecture:")
print("1. Old approach: Direct HTTP API (now deprecated/404)")
print("2. New approach: On-chain Data Streams via Verifier contracts")
print()
print("Data Streams require:")
print("  - Stream ID (feed ID like the ones we have)")
print("  - Verifier contract address (network-specific)")
print("  - ABI to call verifier.latestReport(feedId) or similar")
print()
print("Networks where Data Streams are available:")
print("  - Arbitrum One (low cost)")
print("  - Base (low cost)")
print("  - Avalanche")
print("  - Optimism")
print()
print("Next steps:")
print("1. Find the exact Verifier contract address for the network")
print("2. Get the ABI for reading reports")
print("3. Decode the report to extract price and timestamp")
print()

# Try a simple test with known Chainlink Price Feed (different from Data Streams)
# Classic Price Feeds are simpler and still work
print("Testing Classic Chainlink Price Feed (for comparison)...")
print("-" * 70)

# BTC/USD Price Feed on Arbitrum One
# Address from: https://docs.chain.link/data-feeds/price-feeds/addresses?network=arbitrum
BTC_USD_FEED_ARBITRUM = "0x6ce185860a4963106506C203335A2910413708e9"

# Simplified ABI for AggregatorV3Interface
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
    }
]
''')

try:
    w3 = Web3(Web3.HTTPProvider("https://arb1.arbitrum.io/rpc", request_kwargs={'timeout': 15}))
    if w3.is_connected():
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(BTC_USD_FEED_ARBITRUM),
            abi=AGGREGATOR_V3_ABI
        )
        
        # Get decimals
        decimals = contract.functions.decimals().call()
        print(f"Feed decimals: {decimals}")
        
        # Get latest price
        round_data = contract.functions.latestRoundData().call()
        round_id, answer, started_at, updated_at, answered_in_round = round_data
        
        price = answer / (10 ** decimals)
        
        print(f"BTC/USD (Classic Feed): ${price:,.2f}")
        print(f"Updated at: {updated_at} (timestamp)")
        print()
        print("✓ Classic Price Feeds work!")
        print()
        print("NOTE: Classic Price Feeds ≠ Data Streams")
        print("Data Streams are newer, higher-frequency, different contract interface")
        
except Exception as e:
    print(f"Error testing classic feed: {e}")

print()
print("=" * 70)
print("CONCLUSION")
print("=" * 70)
print("Need to determine:")
print("1. Does Polymarket use Classic Price Feeds or Data Streams?")
print("2. If Data Streams, what is the Verifier contract address?")
print("3. If Classic Feeds, what are the feed addresses for all symbols?")
