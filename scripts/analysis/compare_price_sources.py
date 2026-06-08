"""Compare price sources: Chainlink On-Chain vs Kraken vs CoinGecko"""

import asyncio
import ssl
from datetime import datetime, timezone
import aiohttp
from web3 import Web3

# Chainlink config
CHAINLINK_RPC_URL = "https://arb1.arbitrum.io/rpc"
CHAINLINK_FEEDS = {
    "BTCUSD": "0x6ce185860a4963106506C203335A2910413708e9",
    "ETHUSD": "0x639Fe6ab55C921f74e7fac1ee960C0B6293ba612",
    "SOLUSD": "0x24ceA4b8ce57cdA5058b924B9B9987992450590c",
    "XRPUSD": "0xB4AD57B52aB9141de9926a3e0C8dc6264c2ef205",
}

CHAINLINK_ABI = [
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

# Kraken config
KRAKEN_URL = "https://api.kraken.com/0/public/Ticker"
KRAKEN_PAIRS = {
    "BTCUSD": "BTCUSD",
    "ETHUSD": "ETHUSD",
    "SOLUSD": "SOLUSD",
    "XRPUSD": "XRPUSD",
}

# CoinGecko config
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
COINGECKO_IDS = {
    "BTCUSD": "bitcoin",
    "ETHUSD": "ethereum",
    "SOLUSD": "solana",
    "XRPUSD": "ripple",
}

# SSL no verify
_SSL_NO_VERIFY = ssl.create_default_context()
_SSL_NO_VERIFY.check_hostname = False
_SSL_NO_VERIFY.verify_mode = ssl.CERT_NONE


def fetch_chainlink_sync(symbol):
    """Fetch from Chainlink on-chain (synchronous)"""
    try:
        w3 = Web3(Web3.HTTPProvider(CHAINLINK_RPC_URL, request_kwargs={'timeout': 15}))
        
        if not w3.is_connected():
            return None, "Not connected"
        
        feed_address = CHAINLINK_FEEDS[symbol]
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(feed_address),
            abi=CHAINLINK_ABI
        )
        
        decimals = contract.functions.decimals().call()
        round_data = contract.functions.latestRoundData().call()
        
        answer = round_data[1]
        price = answer / (10 ** decimals)
        
        return price, None
    except Exception as e:
        return None, str(e)[:80]


async def fetch_kraken(session, symbol):
    """Fetch from Kraken"""
    try:
        pair = KRAKEN_PAIRS[symbol]
        
        async with session.get(
            KRAKEN_URL,
            params={"pair": pair},
            ssl=_SSL_NO_VERIFY,
            allow_redirects=False,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            if r.status != 200:
                return None, f"Status {r.status}"
            data = await r.json()
        
        errors = data.get("error") or []
        if errors:
            return None, f"Errors: {errors}"
        
        result = next(iter(data["result"].values()))
        price = float(result["c"][0])
        
        return price, None
    except Exception as e:
        return None, str(e)[:80]


async def fetch_coingecko(session, symbol):
    """Fetch from CoinGecko"""
    try:
        coin_id = COINGECKO_IDS[symbol]
        
        async with session.get(
            COINGECKO_URL,
            params={"ids": coin_id, "vs_currencies": "usd"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            if r.status != 200:
                return None, f"Status {r.status}"
            data = await r.json()
        
        if coin_id not in data or "usd" not in data[coin_id]:
            return None, "Missing data"
        
        price = float(data[coin_id]["usd"])
        
        return price, None
    except Exception as e:
        return None, str(e)[:80]


async def main():
    print("=" * 80)
    print("PRICE SOURCE COMPARISON")
    print(f"Timestamp: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 80)
    print()
    
    async with aiohttp.ClientSession() as session:
        for symbol in ["BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD"]:
            print(f"\n{symbol}:")
            print("-" * 40)
            
            # Fetch Chainlink (sync)
            chainlink_price, chainlink_err = await asyncio.get_event_loop().run_in_executor(
                None, fetch_chainlink_sync, symbol
            )
            
            # Fetch Kraken and CoinGecko (async)
            kraken_price, kraken_err = await fetch_kraken(session, symbol)
            coingecko_price, coingecko_err = await fetch_coingecko(session, symbol)
            
            # Display results
            if chainlink_price:
                print(f"  Chainlink:  ${chainlink_price:,.2f}")
            else:
                print(f"  Chainlink:  ERROR - {chainlink_err}")
            
            if kraken_price:
                print(f"  Kraken:     ${kraken_price:,.2f}")
                if chainlink_price:
                    diff = kraken_price - chainlink_price
                    pct = (diff / chainlink_price) * 100
                    print(f"              Δ {diff:+.2f} ({pct:+.3f}%)")
            else:
                print(f"  Kraken:     ERROR - {kraken_err}")
            
            if coingecko_price:
                print(f"  CoinGecko:  ${coingecko_price:,.2f}")
                if chainlink_price:
                    diff = coingecko_price - chainlink_price
                    pct = (diff / chainlink_price) * 100
                    print(f"              Δ {diff:+.2f} ({pct:+.3f}%)")
            else:
                print(f"  CoinGecko:  ERROR - {coingecko_err}")
            
            # Determine closest
            if chainlink_price:
                closest = None
                min_diff = float('inf')
                
                if kraken_price:
                    diff = abs(kraken_price - chainlink_price)
                    if diff < min_diff:
                        min_diff = diff
                        closest = "Kraken"
                
                if coingecko_price:
                    diff = abs(coingecko_price - chainlink_price)
                    if diff < min_diff:
                        min_diff = diff
                        closest = "CoinGecko"
                
                if closest:
                    print(f"\n  ✓ Closest to Chainlink: {closest}")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
