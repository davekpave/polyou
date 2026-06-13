"""refresh_leader_pool.py

Weekly job: discover new high-performing traders from recent Polymarket
15m crypto markets and merge them into logs/oos_top_traders.csv so the
paper bot starts tracking them.

Does NOT remove existing leaders — only adds new candidates that meet
the minimum EV and trade-count thresholds.

Designed to run via systemd weekly timer (Sunday 03:00 UTC, before the
04:00 rebalancer) or manually:

    python3 src/refresh_leader_pool.py

Env vars (all optional):
    REBAL_OOS_FILE          path to oos_top_traders.csv
    REFRESH_LOOKBACK_DAYS   how far back to sample markets (default 30)
    REFRESH_MIN_TRADES      min trades for a new candidate (default 20)
    REFRESH_MIN_EV          min EV/dollar for a new candidate (default 0.05)
    REFRESH_MAX_NEW         max new addresses added per run (default 20)
"""
from __future__ import annotations

import csv
import json
import logging
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("refresh_leader_pool")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GAMMA_API = "https://gamma-api.polymarket.com/markets"
DATA_API  = "https://data-api.polymarket.com/trades"
SLUG_RE   = re.compile(r"^(btc|eth|sol|xrp)-updown-15m-\d+$")
HEADERS   = {"User-Agent": "Mozilla/5.0 polyou-refresh"}

OOS_FILE      = Path(os.getenv("REBAL_OOS_FILE", "/root/polyou/logs/oos_top_traders.csv"))
LOOKBACK_DAYS = int(os.getenv("REFRESH_LOOKBACK_DAYS", "30"))
MIN_TRADES    = int(os.getenv("REFRESH_MIN_TRADES",    "20"))
MIN_EV        = float(os.getenv("REFRESH_MIN_EV",      "0.05"))
MAX_NEW       = int(os.getenv("REFRESH_MAX_NEW",        "20"))

OOS_FIELDS = [
    "address", "train_pnl", "train_n", "train_vol",
    "test_pnl", "test_n", "test_vol", "test_ev_per_dollar",
]

# ---------------------------------------------------------------------------
# P&L helper (mirrors oos_validate.py trade_pnl)
# ---------------------------------------------------------------------------
def trade_pnl(side: str, asset: str, size: float, price: float, winner: str):
    """Return (pnl, cash_at_risk) for a single BUY or SELL trade."""
    won = (asset == winner)
    if side == "BUY":
        return (size * (1.0 - price) if won else -size * price), price * size
    if side == "SELL":
        return (-size * (1.0 - price) if won else size * price), price * size
    return 0.0, 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_existing() -> dict[str, dict]:
    """Return {address_lower: row_dict} for all rows in oos_top_traders.csv."""
    if not OOS_FILE.exists():
        logger.warning("OOS file not found: %s", OOS_FILE)
        return {}
    with OOS_FILE.open(encoding="utf-8") as f:
        return {r["address"].lower(): r for r in csv.DictReader(f)}


def save_pool(rows: dict[str, dict]) -> None:
    OOS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = OOS_FILE.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OOS_FIELDS, extrasaction="ignore")
        w.writeheader()
        # Keep sorted by test_ev_per_dollar descending
        for row in sorted(
            rows.values(),
            key=lambda r: float(r.get("test_ev_per_dollar") or 0),
            reverse=True,
        ):
            w.writerow(row)
    tmp.replace(OOS_FILE)
    logger.info("Saved %d rows to %s", len(rows), OOS_FILE)


def _get_json(client: httpx.Client, url: str, params: dict, retries: int = 5) -> Optional[list | dict]:
    for attempt in range(retries):
        try:
            r = client.get(url, params=params, timeout=30, headers=HEADERS)
            if r.status_code == 429:
                wait = 2.0 * (attempt + 1)
                logger.debug("Rate limited; sleeping %.1fs", wait)
                time.sleep(wait)
                continue
            if r.status_code == 400:
                return None
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == retries - 1:
                logger.debug("Request failed after %d attempts: %s", retries, e)
                return None
            time.sleep(1.0 * (attempt + 1))
    return None


# ---------------------------------------------------------------------------
# Market discovery
# ---------------------------------------------------------------------------
def fetch_recent_markets(client: httpx.Client) -> list[dict]:
    """Return list of {conditionId, winner_token} for resolved 15m markets
    in the last LOOKBACK_DAYS days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    markets: list[dict] = []
    offset = 0

    while True:
        params = {
            "closed": "true",
            "limit": 500,
            "offset": offset,
            "end_date_min": cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        batch = _get_json(client, GAMMA_API, params)
        if not batch or not isinstance(batch, list):
            break

        for m in batch:
            slug = m.get("slug", "")
            if not SLUG_RE.match(slug):
                continue

            cond = m.get("conditionId", "")
            if not cond:
                continue

            # Determine winner token from final settlement prices
            try:
                tokens = json.loads(m.get("clobTokenIds") or "[]")
                prices = [float(x) for x in json.loads(m.get("outcomePrices") or "[]")]
            except Exception:
                continue

            if len(tokens) != 2 or len(prices) != 2:
                continue

            if prices[0] >= 0.99 and prices[1] <= 0.01:
                winner_token = tokens[0]
            elif prices[1] >= 0.99 and prices[0] <= 0.01:
                winner_token = tokens[1]
            else:
                continue  # market not cleanly resolved

            markets.append({"condition_id": cond, "winner_token": winner_token})

        if len(batch) < 500:
            break
        offset += 500
        time.sleep(0.1)

    logger.info("Found %d resolved 15m markets in last %d days", len(markets), LOOKBACK_DAYS)
    return markets


# ---------------------------------------------------------------------------
# Trade scoring
# ---------------------------------------------------------------------------
def score_market_traders(
    client: httpx.Client,
    condition_id: str,
    winner_token: str,
    stats: dict,
) -> None:
    """Fetch first page of trades for a market and accumulate per-trader stats."""
    data = _get_json(client, DATA_API, {"market": condition_id, "limit": 500})
    if not data or not isinstance(data, list):
        return

    for t in data:
        addr = (t.get("proxyWallet") or "").lower()
        if not addr or not addr.startswith("0x"):
            continue
        side = (t.get("side") or "").upper()
        try:
            size  = float(t.get("size")  or 0)
            price = float(t.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if size <= 0 or price <= 0:
            continue
        asset = str(t.get("asset") or "")
        pnl, cash = trade_pnl(side, asset, size, price, winner_token)
        s = stats[addr]
        s["pnl"]  += pnl
        s["n"]    += 1
        s["cash"] += cash


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    logger.info("=== refresh_leader_pool start ===")
    existing = load_existing()
    logger.info("Existing pool: %d leaders", len(existing))

    with httpx.Client(timeout=30) as client:
        markets = fetch_recent_markets(client)
        if not markets:
            logger.warning("No markets found; exiting")
            return

        stats: dict[str, dict] = defaultdict(lambda: {"pnl": 0.0, "n": 0, "cash": 0.0})
        for i, mkt in enumerate(markets):
            score_market_traders(client, mkt["condition_id"], mkt["winner_token"], stats)
            if (i + 1) % 50 == 0:
                logger.info("Processed %d / %d markets ...", i + 1, len(markets))
            time.sleep(0.05)  # gentle rate limiting

    logger.info("Scored %d unique addresses across %d markets", len(stats), len(markets))

    # Filter to new qualifying candidates
    candidates = []
    for addr, s in stats.items():
        if addr in existing:
            continue
        if s["n"] < MIN_TRADES:
            continue
        ev = s["pnl"] / s["cash"] if s["cash"] > 0 else 0.0
        if ev < MIN_EV:
            continue
        candidates.append((addr, s, ev))

    candidates.sort(key=lambda x: x[2], reverse=True)
    logger.info("New qualifying candidates: %d (cap=%d)", len(candidates), MAX_NEW)

    new_added = 0
    for addr, s, ev in candidates[:MAX_NEW]:
        vol = s["cash"]
        logger.info(
            "  + %s  n=%d  ev=%.4f  pnl=%.2f  vol=%.2f",
            addr[:18], s["n"], ev, s["pnl"], vol,
        )
        existing[addr] = {
            "address":            addr,
            "train_pnl":          f"{s['pnl']:.2f}",
            "train_n":            s["n"],
            "train_vol":          f"{vol:.2f}",
            "test_pnl":           f"{s['pnl']:.2f}",
            "test_n":             s["n"],
            "test_vol":           f"{vol:.2f}",
            "test_ev_per_dollar": f"{ev:.6f}",
        }
        new_added += 1

    if new_added:
        save_pool(existing)
        logger.info("Added %d new leaders; pool now %d total", new_added, len(existing))
    else:
        logger.info("No new qualifying leaders found; pool unchanged")

    logger.info("=== refresh_leader_pool done ===")


if __name__ == "__main__":
    main()
