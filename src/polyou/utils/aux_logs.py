"""
Auxiliary CSV writers for data-collection-only telemetry.

Pure observers — never raise into the caller, never feed any decision.
All writers append to logs/<file>.csv with extrasaction="ignore" so adding
columns later is safe.

Files produced:
  - trade_gates.csv          one row per gate per TRADE/READ_ONLY decision
  - cooldown_events.csv      cooldown set / observed / cleared
  - confirmation_events.csv  every increment / clear of _signal_confirmations
  - side_imbalance.csv       YES vs NO book snapshot at decision time
  - price_source_ticks.csv   which fallback source supplied each tick
  - ops_health.csv           WS crash / stall, CLOB 429 / timeout, order retry
"""

from __future__ import annotations

import csv
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

logger = logging.getLogger("aux_logs")

LOG_DIR = "logs"

TRADE_GATES_PATH = os.path.join(LOG_DIR, "trade_gates.csv")
COOLDOWN_EVENTS_PATH = os.path.join(LOG_DIR, "cooldown_events.csv")
CONFIRMATION_EVENTS_PATH = os.path.join(LOG_DIR, "confirmation_events.csv")
SIDE_IMBALANCE_PATH = os.path.join(LOG_DIR, "side_imbalance.csv")
PRICE_SOURCE_TICKS_PATH = os.path.join(LOG_DIR, "price_source_ticks.csv")
OPS_HEALTH_PATH = os.path.join(LOG_DIR, "ops_health.csv")

TRADE_GATES_FIELDS = (
    "ts_iso",
    "decision_type",      # TRADE | READ_ONLY (we log both — the diagnostic value is the same)
    "symbol",
    "side",
    "token_id",
    "window_start_ts",
    "gate_name",
    "passed",             # 1/0; "" if non-boolean (e.g. continuation_override "True")
    "raw_value",          # str(gate_value)
)

COOLDOWN_EVENTS_FIELDS = (
    "ts_iso",
    "event",              # SET | OBSERVED_BLOCK | EXPIRED
    "reason",
    "loss_window_end_ts",
    "cooldown_until_window_ts",
    "skip_windows",
    "current_window_end_ts",
)

CONFIRMATION_EVENTS_FIELDS = (
    "ts_iso",
    "event",              # INCREMENT | CLEAR
    "symbol",
    "side",
    "count",
    "required",
    "trigger",            # caller-supplied label of WHY it changed
)

SIDE_IMBALANCE_FIELDS = (
    "ts_iso",
    "symbol",
    "contract_slug",
    "window_start_ts",
    "decided_side",
    "yes_token_id",
    "no_token_id",
    "yes_best_bid",
    "yes_best_ask",
    "yes_best_bid_size",
    "yes_best_ask_size",
    "yes_mid",
    "yes_spread_bps",
    "no_best_bid",
    "no_best_ask",
    "no_best_bid_size",
    "no_best_ask_size",
    "no_mid",
    "no_spread_bps",
    "mid_sum",            # yes_mid + no_mid (should ~= 1.0; deviation is arb signal)
    "size_imbalance",     # (yes_bid_size - no_bid_size) / (yes+no)
    "yes_clob_age_ms",
    "no_clob_age_ms",
)

PRICE_SOURCE_TICKS_FIELDS = (
    "ts_iso",
    "symbol",
    "source",             # CHAINLINK_ONCHAIN | KRAKEN | COINGECKO | CHAINLINK_HTTP
    "price",
    "oracle_ts",
    "fetch_latency_ms",
)

OPS_HEALTH_FIELDS = (
    "ts_iso",
    "component",          # chainlink_streams | clob_book | execution_client
    "event",              # WS_CRASH | STALL | CLOB_429 | CLOB_TIMEOUT | ORDER_RETRY | ORDER_FAIL | ANCHOR_LATENCY
    "symbol",
    "detail",
    "latency_ms",
)


def _append(path: str, fields: Iterable[str], row: dict) -> None:
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        new_file = not os.path.isfile(path)
        with open(path, mode="a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=tuple(fields), extrasaction="ignore")
            if new_file:
                writer.writeheader()
            writer.writerow(row)
    except Exception:
        logger.exception("aux_logs CSV write failed | path=%s", path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ----------------------------------------------------------------------
# trade_gates.csv
# ----------------------------------------------------------------------

def log_trade_gates(
    *,
    decision_type: str,
    symbol: str,
    side: str,
    token_id: str,
    window_start_ts: Optional[int],
    gates: dict,
) -> None:
    if not gates:
        return
    ts = _now_iso()
    for name, val in gates.items():
        if isinstance(val, bool):
            passed = "1" if val else "0"
        elif isinstance(val, (int, float)) and val in (0, 1):
            passed = "1" if val else "0"
        else:
            passed = ""
        _append(TRADE_GATES_PATH, TRADE_GATES_FIELDS, {
            "ts_iso": ts,
            "decision_type": decision_type,
            "symbol": symbol,
            "side": side,
            "token_id": token_id,
            "window_start_ts": window_start_ts if window_start_ts is not None else "",
            "gate_name": name,
            "passed": passed,
            "raw_value": str(val),
        })


# ----------------------------------------------------------------------
# cooldown_events.csv
# ----------------------------------------------------------------------

def log_cooldown_event(
    *,
    event: str,
    reason: str = "",
    loss_window_end_ts: Optional[int] = None,
    cooldown_until_window_ts: Optional[int] = None,
    skip_windows: Optional[int] = None,
    current_window_end_ts: Optional[int] = None,
) -> None:
    _append(COOLDOWN_EVENTS_PATH, COOLDOWN_EVENTS_FIELDS, {
        "ts_iso": _now_iso(),
        "event": event,
        "reason": reason,
        "loss_window_end_ts": loss_window_end_ts if loss_window_end_ts is not None else "",
        "cooldown_until_window_ts": cooldown_until_window_ts if cooldown_until_window_ts is not None else "",
        "skip_windows": skip_windows if skip_windows is not None else "",
        "current_window_end_ts": current_window_end_ts if current_window_end_ts is not None else "",
    })


# ----------------------------------------------------------------------
# confirmation_events.csv
# ----------------------------------------------------------------------

def log_confirmation_event(
    *,
    event: str,
    symbol: str,
    side: str,
    count: Optional[int] = None,
    required: Optional[int] = None,
    trigger: str = "",
) -> None:
    _append(CONFIRMATION_EVENTS_PATH, CONFIRMATION_EVENTS_FIELDS, {
        "ts_iso": _now_iso(),
        "event": event,
        "symbol": symbol,
        "side": side,
        "count": count if count is not None else "",
        "required": required if required is not None else "",
        "trigger": trigger,
    })


# ----------------------------------------------------------------------
# side_imbalance.csv
# ----------------------------------------------------------------------

def log_side_imbalance(
    *,
    symbol: str,
    contract_slug: str,
    window_start_ts: Optional[int],
    decided_side: str,
    yes_token_id: str,
    no_token_id: str,
    clob_book_tracker,
) -> None:
    """Snapshot YES + NO books at decision time. Tolerant to None tracker."""
    if clob_book_tracker is None:
        return
    try:
        yes_snap = clob_book_tracker.get_book(yes_token_id) if yes_token_id else None
        no_snap = clob_book_tracker.get_book(no_token_id) if no_token_id else None
        yes_age = clob_book_tracker.get_age_ms(yes_token_id) if yes_token_id else None
        no_age = clob_book_tracker.get_age_ms(no_token_id) if no_token_id else None
    except Exception:
        logger.exception("side_imbalance: tracker read failed")
        return

    def _f(v, dec=4):
        if v is None:
            return ""
        try:
            return f"{float(v):.{dec}f}"
        except Exception:
            return ""

    def _book_fields(snap):
        if snap is None:
            return None, None, None, None, None, None
        ba = getattr(snap, "best_ask", None)
        bb = getattr(snap, "best_bid", None)
        bas = getattr(snap, "best_ask_size", None)
        bbs = getattr(snap, "best_bid_size", None)
        mid = None
        if isinstance(ba, (int, float)) and isinstance(bb, (int, float)):
            mid = (ba + bb) / 2.0
        spread_bps = None
        if mid and isinstance(ba, (int, float)) and isinstance(bb, (int, float)) and mid > 0:
            spread_bps = (ba - bb) / mid * 10000.0
        return ba, bb, bas, bbs, mid, spread_bps

    yba, ybb, ybas, ybbs, ymid, ysp = _book_fields(yes_snap)
    nba, nbb, nbas, nbbs, nmid, nsp = _book_fields(no_snap)

    mid_sum = ""
    if isinstance(ymid, (int, float)) and isinstance(nmid, (int, float)):
        mid_sum = f"{ymid + nmid:.4f}"

    size_imb = ""
    try:
        ys = float(ybbs or 0.0)
        ns = float(nbbs or 0.0)
        if ys + ns > 0:
            size_imb = f"{(ys - ns) / (ys + ns):.4f}"
    except Exception:
        pass

    _append(SIDE_IMBALANCE_PATH, SIDE_IMBALANCE_FIELDS, {
        "ts_iso": _now_iso(),
        "symbol": symbol,
        "contract_slug": contract_slug,
        "window_start_ts": window_start_ts if window_start_ts is not None else "",
        "decided_side": decided_side,
        "yes_token_id": yes_token_id or "",
        "no_token_id": no_token_id or "",
        "yes_best_bid": _f(ybb),
        "yes_best_ask": _f(yba),
        "yes_best_bid_size": _f(ybbs, 2),
        "yes_best_ask_size": _f(ybas, 2),
        "yes_mid": _f(ymid),
        "yes_spread_bps": _f(ysp, 1),
        "no_best_bid": _f(nbb),
        "no_best_ask": _f(nba),
        "no_best_bid_size": _f(nbbs, 2),
        "no_best_ask_size": _f(nbas, 2),
        "no_mid": _f(nmid),
        "no_spread_bps": _f(nsp, 1),
        "mid_sum": mid_sum,
        "size_imbalance": size_imb,
        "yes_clob_age_ms": yes_age if yes_age is not None else "",
        "no_clob_age_ms": no_age if no_age is not None else "",
    })


# ----------------------------------------------------------------------
# price_source_ticks.csv
# ----------------------------------------------------------------------

def log_price_source_tick(
    *,
    symbol: str,
    source: str,
    price: float,
    oracle_ts: float,
    fetch_latency_ms: Optional[float] = None,
) -> None:
    _append(PRICE_SOURCE_TICKS_PATH, PRICE_SOURCE_TICKS_FIELDS, {
        "ts_iso": _now_iso(),
        "symbol": symbol,
        "source": source,
        "price": f"{price:.8f}",
        "oracle_ts": f"{oracle_ts:.3f}",
        "fetch_latency_ms": f"{fetch_latency_ms:.1f}" if fetch_latency_ms is not None else "",
    })


# ----------------------------------------------------------------------
# ops_health.csv
# ----------------------------------------------------------------------

def log_ops_health(
    *,
    component: str,
    event: str,
    symbol: str = "",
    detail: str = "",
    latency_ms: Optional[float] = None,
) -> None:
    _append(OPS_HEALTH_PATH, OPS_HEALTH_FIELDS, {
        "ts_iso": _now_iso(),
        "component": component,
        "event": event,
        "symbol": symbol,
        "detail": detail[:200] if detail else "",
        "latency_ms": f"{latency_ms:.1f}" if latency_ms is not None else "",
    })
