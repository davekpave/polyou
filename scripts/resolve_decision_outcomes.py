"""Post-hoc resolver for the bot's decision and block logs.

Processes up to three input files (each is optional — missing files are skipped):

    logs/decision_log.csv   ->  logs/decision_log_resolved.csv
    logs/gate_blocks.csv    ->  logs/gate_blocks_resolved.csv
    logs/rr_blocks.csv      ->  logs/rr_blocks_resolved.csv

For every row whose 15-minute UpDown window has already closed, queries the
Polymarket Gamma API to find which side won, then writes a sidecar CSV with
three appended columns:

    resolved_winner          UP | DOWN | UNRESOLVED | PENDING | ERROR
    would_have_won           1 | 0 | ""   (empty if side missing or unresolved)
    payoff_per_dollar        (1 - snapshot_price)  if win
                             -snapshot_price       if loss
                             ""                    otherwise

The block logs don't carry a contract_slug column — it is derived from
`symbol` + `window_start_ts` using the same convention the live bot uses
(see polyou.markets.polymarket_crypto_resolver.CRYPTO_SLUG_MAP).

Idempotent: a single shared JSON cache keyed by contract_slug avoids
re-querying already-resolved windows on subsequent runs. A typical week of
gate_blocks shares only a few hundred unique windows, so the API cost is
small even for 50k+ row inputs.

Read-only with respect to the live bot. Safe to run while the bot is up.

Usage:
    .venv\\Scripts\\python.exe scripts\\resolve_decision_outcomes.py
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
from typing import Dict, List, Tuple

import requests

GAMMA_BASE = "https://gamma-api.polymarket.com"
LOGS_DIR = "logs"
CACHE_PATH = os.path.join("logs", "derived", "outcome_cache.json")

REQUEST_TIMEOUT = 10
SLEEP_BETWEEN_REQUESTS = 0.10  # be polite to gamma

NEW_FIELDS = ("resolved_winner", "would_have_won", "payoff_per_dollar")

# Mirrors src/polyou/markets/polymarket_crypto_resolver.py CRYPTO_SLUG_MAP.
# Symbols in the block logs come through as "BTCUSD", "ETHUSD", etc.
SYMBOL_TO_SLUG_PREFIX = {
    "BTCUSD": "btc",
    "ETHUSD": "eth",
    "SOLUSD": "sol",
    "XRPUSD": "xrp",
}

# Each input file: derive_slug=True means the row has no contract_slug
# column and we must build it from symbol + window_start_ts.
# `sources` is a list of CSVs that get unioned (column-wise NaN fill on
# missing fields) into one combined stream before resolution. This lets
# us transparently ingest archived schemas (e.g. *_v1.csv) alongside the
# current file. `path` is the canonical name used for stats display.
INPUTS = [
    {
        "path": os.path.join(LOGS_DIR, "decision_log.csv"),
        "sources": [os.path.join(LOGS_DIR, "decision_log.csv")],
        "out":  os.path.join(LOGS_DIR, "decision_log_resolved.csv"),
        "derive_slug": False,
    },
    {
        "path": os.path.join(LOGS_DIR, "gate_blocks.csv"),
        "sources": [
            os.path.join(LOGS_DIR, "gate_blocks_v1.csv"),
            os.path.join(LOGS_DIR, "gate_blocks_v2.csv"),
            os.path.join(LOGS_DIR, "gate_blocks.csv"),
        ],
        "out":  os.path.join(LOGS_DIR, "gate_blocks_resolved.csv"),
        "derive_slug": True,
    },
    {
        "path": os.path.join(LOGS_DIR, "rr_blocks.csv"),
        "sources": [
            os.path.join(LOGS_DIR, "rr_blocks_v1.csv"),
            os.path.join(LOGS_DIR, "rr_blocks_v2.csv"),
            os.path.join(LOGS_DIR, "rr_blocks.csv"),
        ],
        "out":  os.path.join(LOGS_DIR, "rr_blocks_resolved.csv"),
        "derive_slug": True,
    },
]


def _load_cache() -> Dict[str, dict]:
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: Dict[str, dict]) -> None:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)
    os.replace(tmp, CACHE_PATH)


def _derive_slug(symbol: str, window_start_ts: str) -> str:
    """Build `{prefix}-updown-15m-{window_start_ts}` from row fields.

    Returns "" if either input is unusable.
    """
    sym = (symbol or "").strip().upper()
    prefix = SYMBOL_TO_SLUG_PREFIX.get(sym)
    if not prefix:
        return ""
    try:
        ws = int(float(window_start_ts))
    except (TypeError, ValueError):
        return ""
    if ws <= 0:
        return ""
    return f"{prefix}-updown-15m-{ws}"


def _resolve_slug(slug: str) -> dict:
    """Return {'winner': UP|DOWN|UNRESOLVED|PENDING|ERROR, 'closed': bool}."""
    try:
        r = requests.get(
            f"{GAMMA_BASE}/events?slug={slug}",
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code != 200:
            return {"winner": "ERROR", "closed": False, "http": r.status_code}
        data = r.json()
        if not data:
            return {"winner": "ERROR", "closed": False, "note": "empty"}

        markets = data[0].get("markets") or []
        if not markets:
            return {"winner": "ERROR", "closed": False, "note": "no markets"}
        m = markets[0]
        closed = bool(m.get("closed", False))

        if not closed:
            return {"winner": "PENDING", "closed": False}

        outcomes = m.get("outcomes") or []
        prices_raw = m.get("outcomePrices") or []
        if isinstance(outcomes, str):
            try:
                outcomes = json.loads(outcomes)
            except Exception:
                pass
        if isinstance(prices_raw, str):
            try:
                prices_raw = json.loads(prices_raw)
            except Exception:
                prices_raw = []

        winner = "UNRESOLVED"
        for i, p in enumerate(prices_raw):
            if str(p) == "1" and i < len(outcomes):
                winner = str(outcomes[i]).strip().upper()
                break
        if winner not in ("UP", "DOWN"):
            winner = "UNRESOLVED"
        return {"winner": winner, "closed": True}

    except Exception as exc:
        return {"winner": "ERROR", "closed": False, "error": str(exc)}


def _compute_payoff(side: str, winner: str, snapshot_price: str) -> Tuple[str, str]:
    """Return (would_have_won, payoff_per_dollar) as strings."""
    if not side or winner not in ("UP", "DOWN"):
        return ("", "")
    side_u = side.strip().upper()
    if side_u not in ("UP", "DOWN"):
        return ("", "")
    won = side_u == winner
    try:
        sp = float(snapshot_price)
    except (TypeError, ValueError):
        return ("1" if won else "0", "")
    if not (0.0 < sp < 1.0):
        return ("1" if won else "0", "")
    payoff = (1.0 - sp) if won else (-sp)
    return ("1" if won else "0", f"{payoff:.4f}")


def _process_file(
    in_path: str,
    out_path: str,
    derive_slug: bool,
    cache: Dict[str, dict],
    now_ts: float,
    sources: List[str] | None = None,
) -> dict:
    """Resolve outcomes for one CSV. Returns a small stats dict.

    If `sources` is provided, all listed CSVs are read and unioned (with
    NaN-fill on missing columns) into one combined row stream, preserving
    file order. Otherwise falls back to reading just `in_path`.
    """
    stats = {
        "file": in_path,
        "rows": 0,
        "resolved": 0,
        "pending": 0,
        "error": 0,
        "cache_hits": 0,
        "api_calls": 0,
        "wins": 0,
        "scored": 0,
        "payoffs": [],
        "skipped_missing": True,
    }

    src_paths = [p for p in (sources or [in_path]) if os.path.exists(p)]
    if not src_paths:
        return stats

    stats["skipped_missing"] = False
    stats["sources"] = src_paths

    rows: List[dict] = []
    in_fields: List[str] = []
    seen_fields = set()
    for src in src_paths:
        with open(src, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for fn in (reader.fieldnames or []):
                if fn not in seen_fields:
                    in_fields.append(fn)
                    seen_fields.add(fn)
            rows.extend(reader)

    out_fields = list(in_fields)
    for nf in NEW_FIELDS:
        if nf not in out_fields:
            out_fields.append(nf)

    stats["rows"] = len(rows)

    for row in rows:
        side = (row.get("side") or "").strip()
        snapshot_price = (row.get("snapshot_price") or "").strip()
        window_start_ts_str = (row.get("window_start_ts") or "").strip()

        if derive_slug:
            slug = _derive_slug(row.get("symbol", ""), window_start_ts_str)
        else:
            slug = (row.get("contract_slug") or "").strip()
            if not slug:
                slug = _derive_slug(row.get("symbol", ""), window_start_ts_str)

        # Compute window_end_ts. decision_log may have it; for block logs
        # we derive from window_start_ts + 900s (15-minute windows).
        window_end_ts = 0
        wet_str = (row.get("window_end_ts") or "").strip()
        if wet_str:
            try:
                window_end_ts = int(float(wet_str))
            except (TypeError, ValueError):
                window_end_ts = 0
        if not window_end_ts and window_start_ts_str:
            try:
                window_end_ts = int(float(window_start_ts_str)) + 900
            except (TypeError, ValueError):
                window_end_ts = 0

        if not slug:
            row["resolved_winner"] = "ERROR"
            row["would_have_won"] = ""
            row["payoff_per_dollar"] = ""
            stats["error"] += 1
            continue

        # Window not yet closed — definitely pending.
        if window_end_ts and window_end_ts > now_ts:
            row["resolved_winner"] = "PENDING"
            row["would_have_won"] = ""
            row["payoff_per_dollar"] = ""
            stats["pending"] += 1
            continue

        cached = cache.get(slug)
        if cached and cached.get("winner") in ("UP", "DOWN", "UNRESOLVED"):
            winner = cached["winner"]
            stats["cache_hits"] += 1
        else:
            res = _resolve_slug(slug)
            stats["api_calls"] += 1
            time.sleep(SLEEP_BETWEEN_REQUESTS)
            winner = res["winner"]
            if winner in ("UP", "DOWN", "UNRESOLVED"):
                cache[slug] = {"winner": winner, "ts": int(now_ts)}

        row["resolved_winner"] = winner
        if winner in ("UP", "DOWN"):
            won, payoff = _compute_payoff(side, winner, snapshot_price)
            row["would_have_won"] = won
            row["payoff_per_dollar"] = payoff
            stats["resolved"] += 1
            if won in ("0", "1"):
                stats["scored"] += 1
                if won == "1":
                    stats["wins"] += 1
                if payoff:
                    try:
                        stats["payoffs"].append(float(payoff))
                    except ValueError:
                        pass
        else:
            row["would_have_won"] = ""
            row["payoff_per_dollar"] = ""
            if winner == "PENDING":
                stats["pending"] += 1
            elif winner == "ERROR":
                stats["error"] += 1

        # Persist cache periodically so a crash doesn't lose progress.
        if stats["api_calls"] and stats["api_calls"] % 50 == 0:
            _save_cache(cache)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    tmp_out = out_path + ".tmp"
    with open(tmp_out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=out_fields)
        w.writeheader()
        for row in rows:
            for k in out_fields:
                row.setdefault(k, "")
            w.writerow({k: row.get(k, "") for k in out_fields})
    os.replace(tmp_out, out_path)

    return stats


def _print_summary(stats: dict) -> None:
    if stats["skipped_missing"]:
        print(f"[resolve] {stats['file']}: not found, skipped")
        return
    print(
        f"[resolve] {stats['file']}: rows={stats['rows']} "
        f"resolved={stats['resolved']} pending={stats['pending']} "
        f"error={stats['error']} api_calls={stats['api_calls']} "
        f"cache_hits={stats['cache_hits']}"
    )
    if stats["scored"]:
        wr = stats["wins"] / stats["scored"] * 100
        mean_ev = (
            sum(stats["payoffs"]) / len(stats["payoffs"])
            if stats["payoffs"] else 0.0
        )
        print(
            f"[resolve]   would-have winrate: "
            f"{stats['wins']}/{stats['scored']} = {wr:.1f}%   "
            f"mean EV/$={mean_ev:+.4f}"
        )


def main() -> int:
    cache = _load_cache()
    now_ts = time.time()

    any_processed = False
    all_stats: List[dict] = []
    for spec in INPUTS:
        s = _process_file(
            in_path=spec["path"],
            out_path=spec["out"],
            derive_slug=spec["derive_slug"],
            cache=cache,
            now_ts=now_ts,
            sources=spec.get("sources"),
        )
        all_stats.append(s)
        if not s["skipped_missing"]:
            any_processed = True

    _save_cache(cache)

    print()
    for s in all_stats:
        _print_summary(s)

    if not any_processed:
        print("[resolve] no input files found.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
