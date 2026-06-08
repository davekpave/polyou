import logging
import time
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict

import requests

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:
    ET = None

logger = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"
POLYMARKET_BASE = "https://polymarket.com"

CRYPTO_SLUG_MAP = {
    "BTC": "btc",
    "ETH": "eth",
    "SOL": "sol",
    "XRP": "xrp",
}

FIFTEEN_MINUTES_SECONDS = 15 * 60
REQUEST_TIMEOUT = 10

_contract_cache: Dict[str, Dict] = {}


# --------------------------------------------------
# Time helpers
# --------------------------------------------------

def _get_now_et(now_ts: Optional[float] = None) -> datetime:
    if now_ts is not None:
        if ET:
            return datetime.fromtimestamp(now_ts, tz=ET)
        return datetime.utcfromtimestamp(now_ts) - timedelta(hours=5)
    if ET:
        return datetime.now(tz=ET)
    return datetime.utcnow() - timedelta(hours=5)


def _anchor_15m(dt: datetime) -> datetime:
    minute = (dt.minute // 15) * 15
    return dt.replace(minute=minute, second=0, microsecond=0)


def _build_slug(symbol: str, ts: int) -> str:
    return f"{CRYPTO_SLUG_MAP[symbol]}-updown-15m-{ts}"


# --------------------------------------------------
# Resolver (minimal, deterministic)
# --------------------------------------------------

async def resolve_crypto_contract(
    *,
    symbol: str,
    side: Optional[str] = None,
    now_ts: Optional[float] = None,
) -> Optional[Dict]:

    try:
        symbol = symbol.upper()
        if symbol not in CRYPTO_SLUG_MAP:
            logger.warning("[CRYPTO_RESOLVER] Unsupported symbol: %s", symbol)
            return None

        now_et = _get_now_et(now_ts)
        base_window = _anchor_15m(now_et)

        # probe previous, current, next window
        candidate_windows = [
            base_window,
            base_window - timedelta(minutes=15),
            base_window + timedelta(minutes=15),
        ]

        now = now_ts if now_ts is not None else time.time()

        for window_dt in candidate_windows:

            window_start_ts = int(window_dt.timestamp())
            window_end_ts = window_start_ts + FIFTEEN_MINUTES_SECONDS

            cache_key = f"{symbol}:{window_start_ts}"
            cached = _contract_cache.get(cache_key)

            if cached and now < cached["expires_at"]:
                return cached["data"]

            slug = _build_slug(symbol, window_start_ts)

            try:
                resp = requests.get(
                    f"{GAMMA_BASE}/events/slug/{slug}",
                    timeout=REQUEST_TIMEOUT,
                )

                if resp.status_code != 200:
                    continue

                data = resp.json()
                markets = data.get("markets", [])

                if not markets:
                    continue

                market = markets[0]

                result = {
                    "symbol": symbol,
                    "slug": slug,
                    "window_start_ts": window_start_ts,
                    "window_end_ts": window_end_ts,
                    "condition_id": market.get("conditionId"),
                    "yes_token_id": None,
                    "no_token_id": None,
                    "yes_price": None,
                    "no_price": None,
                    "liquidity": market.get("liquidity"),
                    "volume": market.get("volume"),
                    "url": f"{POLYMARKET_BASE}/event/{slug}",
                    "oracle": "uma",
                }

                import json
                
                clob_token_ids = market.get("clobTokenIds")
                if clob_token_ids:
                    if isinstance(clob_token_ids, str):
                        try:
                            clob_token_ids = json.loads(clob_token_ids)
                        except:
                            pass
                    if isinstance(clob_token_ids, list) and len(clob_token_ids) >= 2:
                        result["yes_token_id"] = clob_token_ids[0]
                        result["no_token_id"] = clob_token_ids[1]

                # extract tokens + prices (fallback or override)
                for token in market.get("tokens", []):
                    outcome = str(token.get("outcome", "")).lower()
                    token_id = token.get("tokenId")
                    price = token.get("price")

                    if outcome in ("yes", "up"):
                        result["yes_token_id"] = token_id
                        result["yes_price"] = price
                    elif outcome in ("no", "down"):
                        result["no_token_id"] = token_id
                        result["no_price"] = price

                _contract_cache[cache_key] = {
                    "data": result,
                    "expires_at": window_end_ts,
                }

                logger.info(
                    "[CRYPTO_RESOLVER] Resolved | symbol=%s slug=%s",
                    symbol,
                    slug,
                )

                return result

            except Exception:
                logger.exception("[CRYPTO_RESOLVER] Request failed")

        logger.warning("[CRYPTO_RESOLVER] No match | symbol=%s", symbol)
        return None

    except Exception as e:
        logger.exception("[CRYPTO_RESOLVER_ERROR] %s", e)
        return None
