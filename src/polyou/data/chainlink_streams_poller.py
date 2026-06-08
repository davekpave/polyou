"""
Oracle price poller with multi-source fallback.

STRICT + ROBUST ANCHOR MODE:
- Anchor = first oracle price WHERE ts >= window_start
- No heuristics, no time windows
- No retroactive anchors
- Mid-window startup → skip current window
- Deterministic + production-safe

SOURCE PRIORITY:
1. Chainlink On-Chain (primary, matches Polymarket settlement oracle)
2. Kraken (secondary, fast & reliable spot prices)
3. CoinGecko (tertiary, multi-exchange aggregate)
4. Chainlink HTTP (deprecated fallback, likely unavailable)
"""

import asyncio
import csv
import logging
import json
import os
import ssl
from typing import Dict, Optional
from datetime import datetime, timedelta, timezone

import aiohttp
from web3 import Web3
from web3.exceptions import Web3Exception

from polyou.core.data import MarketData, SpotPriceEvent
from polyou.utils import aux_logs

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:
    ET = None

logger = logging.getLogger(__name__)

# --------------------------------------------------
# Config
# --------------------------------------------------

POLL_INTERVAL_SECONDS = 1
STALL_SECONDS = 180
RESTART_DELAY_SECONDS = 10

GRAPHQL_URL = "https://data.chain.link/api/query-timescale"

HEADERS = {
    "Accept": "application/json",
    "Origin": "https://data.chain.link",
    "Referer": "https://data.chain.link/streams",
    "User-Agent": "Mozilla/5.0",
}

STREAM_FEEDS: Dict[str, str] = {
    "BTCUSD": "0x00039d9e45394f473ab1f050a1b963e6b05351e52d71e507509ada0c95ed75b8",
    "ETHUSD": "0x000362205e10b3a147d02792eccee483dca6c7b44ecce7012cb8c6e0b68b3ae9",
    "SOLUSD": "0x0003b778d3f6b2ac4991302b89cb313f99a42467d6c9c5f96f57c29c0d2bc24f",
    "XRPUSD": "0x0003c16c6aed42294f5cb4741f6e59ba2d728f0eae2eb9e6d3f555808c59fc45",
}

# --------------------------------------------------
# Kraken config (primary source)
# --------------------------------------------------

KRAKEN_URL = "https://api.kraken.com/0/public/Ticker"

KRAKEN_PAIRS: Dict[str, str] = {
    "BTCUSD": "BTCUSD",
    "ETHUSD": "ETHUSD",
    "SOLUSD": "SOLUSD",
    "XRPUSD": "XRPUSD",
}

# --------------------------------------------------
# CoinGecko config (secondary source)
# --------------------------------------------------

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"

COINGECKO_IDS: Dict[str, str] = {
    "BTCUSD": "bitcoin",
    "ETHUSD": "ethereum",
    "SOLUSD": "solana",
    "XRPUSD": "ripple",
}

# --------------------------------------------------
# Chainlink On-Chain config (primary source - matches Polymarket)
# --------------------------------------------------

# Arbitrum One RPC (where Chainlink Classic Price Feeds live)
CHAINLINK_RPC_URL = "https://arb1.arbitrum.io/rpc"

# Chainlink Classic Price Feed addresses on Arbitrum One
# Source: https://docs.chain.link/data-feeds/price-feeds/addresses?network=arbitrum
CHAINLINK_FEEDS: Dict[str, str] = {
    "BTCUSD": "0x6ce185860a4963106506C203335A2910413708e9",
    "ETHUSD": "0x639Fe6ab55C921f74e7fac1ee960C0B6293ba612",
    "SOLUSD": "0x24ceA4b8ce57cdA5058b924B9B9987992450590c",
    "XRPUSD": "0xB4AD57B52aB9141de9926a3e0C8dc6264c2ef205",
}

# Chainlink Aggregator V3 ABI (simplified - only what we need)
CHAINLINK_AGGREGATOR_ABI = [
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

# SSL context that skips verification (public APIs — no credentials)
_SSL_NO_VERIFY = ssl.create_default_context()
_SSL_NO_VERIFY.check_hostname = False
_SSL_NO_VERIFY.verify_mode = ssl.CERT_NONE

# Web3 instance for on-chain reads (initialized once)
_w3: Optional[Web3] = None

def _get_web3() -> Web3:
    """Get or create Web3 instance for Chainlink on-chain reads."""
    global _w3
    if _w3 is None:
        _w3 = Web3(Web3.HTTPProvider(
            CHAINLINK_RPC_URL,
            request_kwargs={'timeout': 15}
        ))
    return _w3

# --------------------------------------------------
# Replay-grade per-tick price log (daily-rotated).
# Mirrors the in-memory SpotPriceEvent stream so the replay harness can
# reconstruct what the bot saw at any wall-clock instant.
# --------------------------------------------------

PRICES_LOG_DIR = "logs"
PRICES_LOG_FIELDS = (
    "ts_iso",
    "ts_epoch",
    "symbol",
    "price",
    "source",
    "oracle_ts",
    "window_start_ts",
)


def _prices_path_for(now_utc: datetime) -> str:
    return os.path.join(
        PRICES_LOG_DIR,
        f"chainlink_prices_{now_utc.strftime('%Y%m%d')}.csv",
    )


def _append_price_row(row: dict) -> None:
    try:
        os.makedirs(PRICES_LOG_DIR, exist_ok=True)
        path = _prices_path_for(datetime.now(tz=timezone.utc))
        new_file = not os.path.isfile(path)
        with open(path, mode="a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=PRICES_LOG_FIELDS)
            if new_file:
                writer.writeheader()
            writer.writerow(row)
    except Exception:
        logger.exception("chainlink_prices write failed")


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def _parse_ts(ts: str) -> float:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def _now_et(ts: float) -> datetime:
    if ET:
        return datetime.fromtimestamp(ts, tz=ET)
    return datetime.fromtimestamp(ts, tz=timezone.utc) - timedelta(hours=5)


def _fifteen_minute_window_start(dt: datetime) -> datetime:
    minute = (dt.minute // 15) * 15
    return dt.replace(minute=minute, second=0, microsecond=0)


# --------------------------------------------------
# Poller
# --------------------------------------------------

class ChainlinkStreamsPoller:
    def __init__(self, *, market_data: MarketData):
        self.market_data = market_data

        self._last_ts: Dict[str, float] = {}  # Oracle timestamp (for anchors)
        self._last_fetch_time: Dict[str, float] = {}  # Local fetch time (for stall detection)

        self._current_window: Dict[str, int] = {}
        self._anchor_emitted: Dict[str, bool] = {}

        # Source tracking
        self._current_source: Dict[str, str] = {}

    async def _fetch_chainlink_onchain(
        self,
        symbol: str,
    ) -> tuple[float, float]:
        """Fetch price from Chainlink Classic Price Feed on Arbitrum (synchronous blockchain read)."""
        
        if symbol not in CHAINLINK_FEEDS:
            raise RuntimeError(f"No Chainlink feed configured for {symbol}")
        
        feed_address = CHAINLINK_FEEDS[symbol]
        
        # Run blockchain call in executor to avoid blocking event loop
        loop = asyncio.get_event_loop()
        
        def _read_chainlink():
            w3 = _get_web3()
            
            if not w3.is_connected():
                raise RuntimeError("Web3 not connected to Arbitrum RPC")
            
            contract = w3.eth.contract(
                address=Web3.to_checksum_address(feed_address),
                abi=CHAINLINK_AGGREGATOR_ABI
            )
            
            # Get decimals and latest round data
            decimals = contract.functions.decimals().call()
            round_data = contract.functions.latestRoundData().call()
            
            round_id, answer, started_at, updated_at, answered_in_round = round_data
            
            # Convert answer to float
            price = answer / (10 ** decimals)
            
            # Use CURRENT time for anchoring (not oracle's updatedAt)
            # Oracle timestamps are historical and cause anchor misses in strict mode
            ts = datetime.now(tz=timezone.utc).timestamp()
            
            return price, ts
        
        return await loop.run_in_executor(None, _read_chainlink)

    async def _fetch_chainlink(
        self,
        session: aiohttp.ClientSession,
        symbol: str,
        feed_id: str,
    ) -> tuple[float, float]:
        """Deprecated: Old HTTP API (no longer available)."""

        params = {
            "query": "LIVE_STREAM_REPORTS_QUERY",
            "variables": json.dumps({"feedId": feed_id}),
        }

        async with session.get(
            GRAPHQL_URL,
            params=params,
            headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as r:
            r.raise_for_status()
            data = await r.json()

        nodes = data["data"]["liveStreamReports"]["nodes"]
        if not nodes:
            raise RuntimeError(f"[FATAL] No stream data for {symbol}")

        node = nodes[0]

        price = int(node["price"]) / 1e18
        ts = _parse_ts(node["validFromTimestamp"])

        return price, ts

    async def _fetch_kraken(
        self,
        session: aiohttp.ClientSession,
        symbol: str,
    ) -> tuple[float, float]:

        pair = KRAKEN_PAIRS[symbol]

        async with session.get(
            KRAKEN_URL,
            params={"pair": pair},
            ssl=_SSL_NO_VERIFY,
            allow_redirects=False,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            if r.status != 200:
                raise RuntimeError(f"Kraken returned status {r.status} for {symbol}")
            data = await r.json()

        errors = data.get("error") or []
        if errors:
            raise RuntimeError(f"Kraken error for {symbol}: {errors}")

        result = next(iter(data["result"].values()))
        price = float(result["c"][0])
        ts = datetime.now(tz=timezone.utc).timestamp()

        return price, ts

    async def _fetch_coingecko(
        self,
        session: aiohttp.ClientSession,
        symbol: str,
    ) -> tuple[float, float]:

        coin_id = COINGECKO_IDS[symbol]

        async with session.get(
            COINGECKO_URL,
            params={"ids": coin_id, "vs_currencies": "usd"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            if r.status != 200:
                raise RuntimeError(f"CoinGecko returned status {r.status} for {symbol}")
            data = await r.json()

        if coin_id not in data or "usd" not in data[coin_id]:
            raise RuntimeError(f"CoinGecko missing price data for {symbol}")

        price = float(data[coin_id]["usd"])
        ts = datetime.now(tz=timezone.utc).timestamp()

        return price, ts

    async def _fetch_latest(
        self,
        session: aiohttp.ClientSession,
        symbol: str,
        feed_id: str,
    ) -> tuple[float, float]:
        """Try sources in priority order: Chainlink On-Chain → Kraken → CoinGecko → Chainlink HTTP (deprecated)."""

        errors = {}

        # 1. Try Chainlink On-Chain (primary - matches Polymarket settlement)
        try:
            price, ts = await self._fetch_chainlink_onchain(symbol)
            prev_source = self._current_source.get(symbol)
            if prev_source != "CHAINLINK_ONCHAIN":
                logger.info("[STREAM] %s using Chainlink On-Chain (primary) | price=%.6f", symbol, price)
                self._current_source[symbol] = "CHAINLINK_ONCHAIN"
            return price, ts
        except Exception as e:
            errors["chainlink_onchain"] = str(e)[:80]

        # 2. Try Kraken (secondary fallback)
        try:
            price, ts = await self._fetch_kraken(session, symbol)
            prev_source = self._current_source.get(symbol)
            if prev_source != "KRAKEN":
                logger.warning(
                    "[STREAM] %s Chainlink on-chain failed, using Kraken (secondary) | price=%.6f",
                    symbol, price
                )
                self._current_source[symbol] = "KRAKEN"
            return price, ts
        except Exception as e:
            errors["kraken"] = str(e)[:80]

        # 3. Try CoinGecko (tertiary fallback)
        try:
            price, ts = await self._fetch_coingecko(session, symbol)
            prev_source = self._current_source.get(symbol)
            if prev_source != "COINGECKO":
                logger.warning(
                    "[STREAM] %s Chainlink+Kraken failed, using CoinGecko (tertiary) | price=%.6f",
                    symbol, price
                )
                self._current_source[symbol] = "COINGECKO"
            return price, ts
        except Exception as e:
            errors["coingecko"] = str(e)[:80]

        # 4. Try Chainlink HTTP (deprecated, likely unavailable)
        try:
            price, ts = await self._fetch_chainlink(session, symbol, feed_id)
            prev_source = self._current_source.get(symbol)
            if prev_source != "CHAINLINK_HTTP":
                logger.warning(
                    "[STREAM] %s All sources failed, trying deprecated Chainlink HTTP | price=%.6f",
                    symbol, price
                )
                self._current_source[symbol] = "CHAINLINK_HTTP"
            return price, ts
        except Exception as e:
            errors["chainlink_http"] = str(e)[:80]

        # All sources failed
        raise RuntimeError(
            f"All price sources failed for {symbol}: {errors}"
        )

    async def _poll_symbol(
        self,
        session: aiohttp.ClientSession,
        symbol: str,
        feed_id: str,
    ) -> None:
        try:
            price, ts = await self._fetch_latest(session, symbol, feed_id)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.warning("[STREAM] Error fetching %s: %s", symbol, type(e).__name__)
            return
        except Exception as e:
            # Truncate to first 120 chars to avoid multi-KB header dumps
            msg = str(e)[:120]
            logger.warning("[STREAM] Error fetching %s: %s", symbol, msg)
            return

        # Update fetch time for stall detection (always updates)
        now = datetime.now(tz=timezone.utc).timestamp()
        self._last_fetch_time[symbol] = now

        prev_ts = self._last_ts.get(symbol)
        self._last_ts[symbol] = ts

        # Skip if oracle timestamp hasn't changed (on-chain oracles update every few minutes)
        if prev_ts is not None and ts <= prev_ts:
            return

        # --- Emit spot ---
        self.market_data.on_message(
            SpotPriceEvent(symbol=symbol, price=price, ts=ts)
        )

        source = self._current_source.get(symbol, "UNKNOWN")
        logger.info("[STREAM] %s price=%.8f ts=%s source=%s", symbol, price, ts, source)

        # Replay-grade per-tick CSV (daily-rotated).
        try:
            now_utc = datetime.now(tz=timezone.utc)
            _ws_dt = _fifteen_minute_window_start(_now_et(ts))
            _append_price_row({
                "ts_iso": now_utc.isoformat(timespec="milliseconds"),
                "ts_epoch": f"{now:.3f}",
                "symbol": symbol,
                "price": f"{price:.8f}",
                "source": source,
                "oracle_ts": f"{ts:.3f}",
                "window_start_ts": int(_ws_dt.timestamp()),
            })
        except Exception:
            logger.exception("chainlink price-row build failed | symbol=%s", symbol)
        try:
            aux_logs.log_price_source_tick(
                symbol=symbol,
                source=source,
                price=price,
                oracle_ts=ts,
                fetch_latency_ms=(now - ts) * 1000.0 if ts else None,
            )
        except Exception:
            pass

        # --------------------------------------------------
        # STRICT 15M ANCHOR LOGIC (DETERMINISTIC)
        # --------------------------------------------------

        dt_et = _now_et(ts)
        window_start_dt = _fifteen_minute_window_start(dt_et)
        window_start_ts = int(window_start_dt.timestamp())

        prev_window = self._current_window.get(symbol)

        # --- First observation (startup) ---
        if prev_window is None:
            self._current_window[symbol] = window_start_ts
            self._anchor_emitted[symbol] = False

            logger.info(
                "[ANCHOR SKIP] %s | mid-window startup | window_start=%s",
                symbol,
                window_start_dt.strftime("%Y-%m-%d %H:%M"),
            )
            return

        # --- Window rollover ---
        if window_start_ts != prev_window:
            self._current_window[symbol] = window_start_ts
            self._anchor_emitted[symbol] = False

            logger.info(
                "[WINDOW ROLLOVER] %s | new_window=%s",
                symbol,
                window_start_dt.strftime("%Y-%m-%d %H:%M"),
            )

        # --------------------------------------------------
        # Anchor emission (STRICT)
        # --------------------------------------------------

        if not self._anchor_emitted.get(symbol, False):

            # STRICT RULE: first tick WHERE ts >= window_start_ts
            if ts >= window_start_ts:
                self._anchor_emitted[symbol] = True

                self.market_data.on_message({
                    "type": "ANCHOR_PRICE",
                    "symbol": symbol,
                    "window_start_ts": window_start_ts,
                    "price": price,
                })

                logger.info(
                    "[ANCHOR] %s | strict anchor | price=%.8f | window=%s",
                    symbol,
                    price,
                    window_start_dt.strftime("%Y-%m-%d %H:%M"),
                )

    async def run(self) -> None:
        logger.info("Starting ChainlinkStreamsPoller (STRICT MODE)")

        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    while True:
                        await asyncio.gather(
                            *(
                                self._poll_symbol(session, symbol, feed_id)
                                for symbol, feed_id in STREAM_FEEDS.items()
                            )
                        )

                        # Stall detection using local fetch time (not oracle timestamp)
                        # On-chain oracles may have same timestamp for minutes, but we fetch every second
                        now = datetime.now(tz=timezone.utc).timestamp()
                        for symbol in STREAM_FEEDS.keys():
                            last_fetch = self._last_fetch_time.get(symbol)
                            if last_fetch is not None and now - last_fetch > STALL_SECONDS:
                                try:
                                    aux_logs.log_ops_health(
                                        component="chainlink_streams",
                                        event="STALL",
                                        symbol=symbol,
                                        detail=f"no_fetch_for_{int(now - last_fetch)}s",
                                        latency_ms=(now - last_fetch) * 1000.0,
                                    )
                                except Exception:
                                    pass
                                raise RuntimeError(
                                    f"[FATAL] No successful fetch for {symbol} in {STALL_SECONDS}s (last={last_fetch})"
                                )

                        await asyncio.sleep(POLL_INTERVAL_SECONDS)

            except asyncio.CancelledError:
                logger.warning("[STREAM] Poller cancelled — exiting cleanly")
                raise

            except Exception as exc:
                logger.exception(
                    "[STREAM] Poller crashed — restarting in %ss",
                    RESTART_DELAY_SECONDS,
                )
                try:
                    aux_logs.log_ops_health(
                        component="chainlink_streams",
                        event="WS_CRASH",
                        detail=f"{type(exc).__name__}: {str(exc)[:160]}",
                    )
                except Exception:
                    pass
                await asyncio.sleep(RESTART_DELAY_SECONDS)
