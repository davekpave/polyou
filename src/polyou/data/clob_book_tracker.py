"""
CLOB Book Tracker — Phase 1 (read-only diagnostic).

Maintains a live in-memory snapshot of best ask/bid for every Polymarket
crypto Up/Down token the bot currently cares about. Pure observer:
- Does NOT feed any trading decision.
- Does NOT replace the existing _fetch_clob_ask_price call path.
- Logs every meaningful ask change so we can measure how fast Polymarket
  reprices versus our own signal classifier.

Tracked set discovery reuses polymarket_crypto_resolver.resolve_crypto_contract
so we hit the same caches and slugs the bot already uses.
"""

from __future__ import annotations

import asyncio
import csv
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Set, Tuple

from polyou.utils import aux_logs

import httpx
import json

from polyou.markets.polymarket_crypto_resolver import resolve_crypto_contract

logger = logging.getLogger("clob_book_tracker")

LOG_DIR = "logs"
CLOB_TICKS_CSV = os.path.join(LOG_DIR, "clob_ticks.csv")
CLOB_TICKS_FIELDS = (
    "ts_iso",
    "symbol",
    "side",
    "window_start_ts",
    "token_id",
    "best_ask",
    "best_bid",
    "best_ask_size",
    "best_bid_size",
    "prev_ask",
    "delta",
    "dt_since_last_s",
    "top5_asks",
    "top5_bids",
)

# Replay-grade per-tick book snapshot. Written on EVERY successful fetch
# (unlike clob_ticks.csv which only writes on ask-change >= 0.5c). Daily
# rotation keeps individual files manageable for backtest replay.
BOOK_SNAPSHOTS_FIELDS = (
    "ts_iso",
    "ts_epoch",
    "symbol",
    "side",
    "window_start_ts",
    "token_id",
    "best_ask",
    "best_bid",
    "best_ask_size",
    "best_bid_size",
    "top5_asks",
    "top5_bids",
)


def _append_csv_row(path: str, fields: Tuple[str, ...], row: dict) -> None:
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        new_file = not os.path.isfile(path)
        with open(path, mode="a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            if new_file:
                writer.writeheader()
            writer.writerow(row)
    except Exception:
        logger.exception("CSV write failed | path=%s", path)


def _book_snapshots_path_for(now_utc: datetime) -> str:
    """Daily-rotated path: logs/book_snapshots_YYYYMMDD.csv (UTC date)."""
    return os.path.join(LOG_DIR, f"book_snapshots_{now_utc.strftime('%Y%m%d')}.csv")

# --------------------------------------------------
# Config
# --------------------------------------------------

POLL_INTERVAL_SECONDS = 2.0          # per-token cadence target
DISCOVERY_INTERVAL_SECONDS = 30.0    # refresh tracked-token set
HTTP_TIMEOUT_SECONDS = 3.0
ASK_CHANGE_LOG_THRESHOLD = 0.005     # log when ask moves >= 0.5c
STALE_AFTER_SECONDS = 10.0           # snapshot considered stale beyond this
CLOB_BOOK_URL = "https://clob.polymarket.com/book"
TOP_N_LEVELS = 5                     # depth captured per side


# --------------------------------------------------
# Snapshot record
# --------------------------------------------------

@dataclass
class BookSnapshot:
    token_id: str
    symbol: str
    side: str               # "YES" or "NO"
    window_start_ts: int
    best_ask: Optional[float]
    best_bid: Optional[float]
    fetched_at: float       # time.time() of successful fetch
    is_stale: bool = False
    # Top-of-book sizes (shares at best_ask / best_bid). Optional to remain
    # backward-compatible with snapshots created before sizes were tracked.
    best_ask_size: Optional[float] = None
    best_bid_size: Optional[float] = None
    # Top-N depth: list of (price, size) pairs, asks ascending, bids descending.
    # Capped at TOP_N_LEVELS. Empty list when book missing.
    top_asks: List[Tuple[float, float]] = None  # type: ignore[assignment]
    top_bids: List[Tuple[float, float]] = None  # type: ignore[assignment]


# --------------------------------------------------
# Tracker
# --------------------------------------------------

class ClobBookTracker:
    """
    Background poller that maintains best-ask/bid for a set of token_ids.

    Phase 1 contract:
      - get_book(token_id) -> BookSnapshot | None     (sync, lock-free read)
      - get_age_ms(token_id) -> int | None
      - run() async loop; cancel to stop.
    """

    def __init__(
        self,
        symbols: Iterable[str],
        *,
        poll_interval: float = POLL_INTERVAL_SECONDS,
        discovery_interval: float = DISCOVERY_INTERVAL_SECONDS,
    ) -> None:
        # symbols are bot-style tickers like "BTCUSD"; resolver uses "BTC".
        self._symbols: Tuple[str, ...] = tuple(symbols)
        self._poll_interval = float(poll_interval)
        self._discovery_interval = float(discovery_interval)

        self._snapshots: Dict[str, BookSnapshot] = {}
        # Last seen ask used to decide when to log a CLOB_TICK.
        self._last_logged_ask: Dict[str, float] = {}
        self._last_logged_at: Dict[str, float] = {}
        # token_id -> (symbol, side, window_start_ts) — owned by discovery.
        self._tracked: Dict[str, Tuple[str, str, int]] = {}
        self._last_discovery_ts: float = 0.0

        self._client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # Public read API (synchronous, safe from any task)
    # ------------------------------------------------------------------

    def get_book(self, token_id: str) -> Optional[BookSnapshot]:
        if not token_id:
            return None
        snap = self._snapshots.get(token_id)
        if snap is None:
            return snap
        # Refresh stale flag on read (no mutation of fetched_at).
        snap.is_stale = (time.time() - snap.fetched_at) >= STALE_AFTER_SECONDS
        return snap

    def get_age_ms(self, token_id: str) -> Optional[int]:
        snap = self._snapshots.get(token_id)
        if snap is None:
            return None
        return int((time.time() - snap.fetched_at) * 1000)

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        logger.info(
            "ClobBookTracker started | symbols=%s poll_interval=%.1fs",
            ",".join(self._symbols),
            self._poll_interval,
        )
        self._client = httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS)
        try:
            while True:
                try:
                    await self._maybe_refresh_tracked_set()
                    await self._poll_cycle()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("ClobBookTracker cycle error")
                    await asyncio.sleep(2.0)
        finally:
            try:
                if self._client is not None:
                    await self._client.aclose()
            except Exception:
                pass
            logger.info("ClobBookTracker stopped")

    # ------------------------------------------------------------------
    # Tracked-set discovery
    # ------------------------------------------------------------------

    async def _maybe_refresh_tracked_set(self) -> None:
        now = time.time()
        if (now - self._last_discovery_ts) < self._discovery_interval and self._tracked:
            return

        new_tracked: Dict[str, Tuple[str, str, int]] = {}
        for sym_full in self._symbols:
            # Bot uses "BTCUSD" but resolver wants "BTC".
            resolver_sym = sym_full[:-3] if sym_full.endswith("USD") else sym_full
            for now_offset in (0.0, 15 * 60.0):
                # Probe current window and the next one so we have the YES/NO
                # tokens before the next window opens.
                try:
                    contract = await resolve_crypto_contract(
                        symbol=resolver_sym,
                        now_ts=now + now_offset,
                    )
                except Exception:
                    logger.exception(
                        "Discovery failed | symbol=%s offset=%.0f",
                        sym_full, now_offset,
                    )
                    continue

                if not contract:
                    continue

                ws = int(contract.get("window_start_ts") or 0)
                yes_id = contract.get("yes_token_id")
                no_id = contract.get("no_token_id")
                if yes_id:
                    new_tracked[str(yes_id)] = (sym_full, "YES", ws)
                if no_id:
                    new_tracked[str(no_id)] = (sym_full, "NO", ws)

        if not new_tracked:
            # Discovery returned nothing — keep old set for now.
            self._last_discovery_ts = now
            return

        added = set(new_tracked.keys()) - set(self._tracked.keys())
        removed = set(self._tracked.keys()) - set(new_tracked.keys())
        self._tracked = new_tracked
        self._last_discovery_ts = now

        if added or removed:
            logger.info(
                "Tracked set refreshed | total=%d added=%d removed=%d",
                len(new_tracked), len(added), len(removed),
            )
            for tok in removed:
                self._snapshots.pop(tok, None)
                self._last_logged_ask.pop(tok, None)
                self._last_logged_at.pop(tok, None)

    # ------------------------------------------------------------------
    # Poll cycle: walk tracked set, pacing to ~poll_interval per token.
    # ------------------------------------------------------------------

    async def _poll_cycle(self) -> None:
        if not self._tracked:
            await asyncio.sleep(self._poll_interval)
            return

        tokens = list(self._tracked.items())
        # Even pacing: total cycle time targets self._poll_interval.
        per_token_sleep = max(0.05, self._poll_interval / max(1, len(tokens)))

        for token_id, (sym, side, ws) in tokens:
            try:
                await self._fetch_and_store(token_id, sym, side, ws)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Poll error | token_id=%s", token_id)
            await asyncio.sleep(per_token_sleep)

    async def _fetch_and_store(
        self, token_id: str, symbol: str, side: str, window_start_ts: int,
    ) -> None:
        assert self._client is not None
        try:
            resp = await self._client.get(
                CLOB_BOOK_URL, params={"token_id": token_id}
            )
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            try:
                aux_logs.log_ops_health(
                    component="clob_book",
                    event="CLOB_TIMEOUT",
                    symbol=symbol,
                    detail=f"{type(exc).__name__}: token={token_id[:16]}",
                )
            except Exception:
                pass
            return  # transient; existing snapshot ages naturally
        if resp.status_code != 200:
            if resp.status_code == 429:
                logger.warning("CLOB 429 rate-limit | token_id=%s", token_id)
                try:
                    aux_logs.log_ops_health(
                        component="clob_book",
                        event="CLOB_429",
                        symbol=symbol,
                        detail=f"token={token_id[:16]}",
                    )
                except Exception:
                    pass
            else:
                try:
                    aux_logs.log_ops_health(
                        component="clob_book",
                        event=f"CLOB_HTTP_{resp.status_code}",
                        symbol=symbol,
                        detail=f"token={token_id[:16]}",
                    )
                except Exception:
                    pass
            return

        try:
            data = resp.json()
        except ValueError:
            return

        best_ask, best_ask_size = _best_level(data.get("asks"), prefer="min")
        best_bid, best_bid_size = _best_level(data.get("bids"), prefer="max")
        top_asks = _top_n_levels(data.get("asks"), prefer="min", n=TOP_N_LEVELS)
        top_bids = _top_n_levels(data.get("bids"), prefer="max", n=TOP_N_LEVELS)

        snap = BookSnapshot(
            token_id=token_id,
            symbol=symbol,
            side=side,
            window_start_ts=window_start_ts,
            best_ask=best_ask,
            best_bid=best_bid,
            fetched_at=time.time(),
            is_stale=False,
            best_ask_size=best_ask_size,
            best_bid_size=best_bid_size,
            top_asks=top_asks,
            top_bids=top_bids,
        )
        self._snapshots[token_id] = snap

        # Replay-grade per-tick snapshot (every successful fetch, daily-rotated).
        try:
            now_utc = datetime.now(timezone.utc)
            _append_csv_row(
                _book_snapshots_path_for(now_utc),
                BOOK_SNAPSHOTS_FIELDS,
                {
                    "ts_iso": now_utc.isoformat(timespec="milliseconds"),
                    "ts_epoch": f"{snap.fetched_at:.3f}",
                    "symbol": symbol,
                    "side": side,
                    "window_start_ts": window_start_ts,
                    "token_id": token_id,
                    "best_ask": f"{best_ask:.4f}" if best_ask is not None else "",
                    "best_bid": f"{best_bid:.4f}" if best_bid is not None else "",
                    "best_ask_size": f"{best_ask_size:.2f}" if best_ask_size is not None else "",
                    "best_bid_size": f"{best_bid_size:.2f}" if best_bid_size is not None else "",
                    "top5_asks": json.dumps(top_asks) if top_asks else "",
                    "top5_bids": json.dumps(top_bids) if top_bids else "",
                },
            )
        except Exception:
            logger.exception("book_snapshots write failed | token_id=%s", token_id)

        if best_ask is None:
            return

        prev = self._last_logged_ask.get(token_id)
        if prev is None or abs(best_ask - prev) >= ASK_CHANGE_LOG_THRESHOLD:
            now = time.time()
            dt = now - self._last_logged_at.get(token_id, now)
            arrow = "→" if prev is not None else "="
            prev_str = f"{prev:.3f}" if prev is not None else "----"
            delta = (best_ask - prev) if prev is not None else 0.0
            logger.info(
                "CLOB_TICK | sym=%s side=%s window=%d ask: %s%s%.3f delta=%+.3f dt=%.1fs",
                symbol, side, window_start_ts, prev_str, arrow, best_ask,
                delta, dt,
            )
            _append_csv_row(
                CLOB_TICKS_CSV,
                CLOB_TICKS_FIELDS,
                {
                    "ts_iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "symbol": symbol,
                    "side": side,
                    "window_start_ts": window_start_ts,
                    "token_id": token_id,
                    "best_ask": f"{best_ask:.4f}",
                    "best_bid": f"{best_bid:.4f}" if best_bid is not None else "",
                    "best_ask_size": f"{best_ask_size:.2f}" if best_ask_size is not None else "",
                    "best_bid_size": f"{best_bid_size:.2f}" if best_bid_size is not None else "",
                    "prev_ask": f"{prev:.4f}" if prev is not None else "",
                    "delta": f"{delta:+.4f}",
                    "dt_since_last_s": f"{dt:.2f}",
                    "top5_asks": json.dumps(top_asks) if top_asks else "",
                    "top5_bids": json.dumps(top_bids) if top_bids else "",
                },
            )
            self._last_logged_ask[token_id] = best_ask
            self._last_logged_at[token_id] = now


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def _best_price(level_rows, *, prefer: str) -> Optional[float]:
    price, _ = _best_level(level_rows, prefer=prefer)
    return price


def _best_level(level_rows, *, prefer: str):
    """Return (best_price, size_at_best). Size is None if missing/unparseable."""
    if not level_rows:
        return None, None
    levels = []
    for row in level_rows:
        try:
            p = float(row["price"])
        except (KeyError, TypeError, ValueError):
            continue
        if p <= 0:
            continue
        try:
            s = float(row.get("size")) if row.get("size") is not None else None
        except (TypeError, ValueError):
            s = None
        levels.append((p, s))
    if not levels:
        return None, None
    best_p = min(p for p, _ in levels) if prefer == "min" else max(p for p, _ in levels)
    # If multiple rows share best price, sum their sizes.
    sizes = [s for p, s in levels if p == best_p and s is not None]
    best_s = sum(sizes) if sizes else None
    return best_p, best_s


def _top_n_levels(level_rows, *, prefer: str, n: int) -> List[Tuple[float, float]]:
    """Return up to n (price, size) pairs, asks ascending or bids descending.

    Aggregates duplicate prices by summing sizes. Skips rows with size=None.
    """
    if not level_rows:
        return []
    agg: Dict[float, float] = {}
    for row in level_rows:
        try:
            p = float(row["price"])
            s = float(row["size"])
        except (KeyError, TypeError, ValueError):
            continue
        if p <= 0 or s <= 0:
            continue
        agg[p] = agg.get(p, 0.0) + s
    if not agg:
        return []
    items = sorted(agg.items(), key=lambda kv: kv[0], reverse=(prefer != "min"))
    # Round to keep CSV cells tight.
    return [(round(p, 4), round(s, 2)) for p, s in items[:n]]
