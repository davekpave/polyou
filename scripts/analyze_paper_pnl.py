"""
Paper P&L summary + 5m window-anchor audit.

Reads logs/shadow_exits.csv (closed positions) and logs/shadow_positions.json
(currently open) and prints:
  - Overall win-rate / total P&L per share
  - Breakdown by symbol and by window length (5m vs 15m)
  - Breakdown by exit_type
  - Anchor audit: for each currently-open 5m / 15m position, compare
    its stored window_start_price against the chainlink stream price
    logged at the window-start timestamp in logs/bot.log.

Pure-read; safe to run while the bot is live.
"""
from __future__ import annotations

import csv
import json
import os
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXITS_CSV = ROOT / "logs" / "shadow_exits.csv"
POSITIONS_JSON = ROOT / "logs" / "shadow_positions.json"
BOT_LOG = ROOT / "logs" / "bot.log"

SLUG_RE = re.compile(r"^(btc|eth|sol|xrp)-updown-(5m|15m)-(\d+)$")
STREAM_RE = re.compile(
    r"\[STREAM\]\s+(BTCUSD|ETHUSD|SOLUSD|XRPUSD)\s+price=([\d.]+)\s+ts=([\d.]+)"
)


def _outcome_from_exit(side: str, exit_type: str, profit: float) -> str:
    # Best-effort win/loss bucket without ground-truth columns.
    # EXPIRY_BID = predicted side near $1 at expiry (likely won).
    # SETTLED_ZERO = predicted side worth $0 at settle (lost).
    if exit_type == "EXPIRY_BID":
        return "WIN"
    if exit_type == "SETTLED_ZERO":
        return "LOSS"
    return "WIN" if profit > 0 else "LOSS"


def summarize_exits():
    if not EXITS_CSV.exists():
        print("(no shadow_exits.csv yet)")
        return
    rows = []
    with open(EXITS_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                r["entry_price"] = float(r["entry_price"])
                r["exit_price"] = float(r["exit_price"])
                r["profit_per_share"] = float(r["profit_per_share"])
            except Exception:
                continue
            rows.append(r)
    if not rows:
        print("(no closed shadow positions yet)")
        return

    print(f"\n=== Shadow exits ({len(rows)} closed positions) ===")
    total_pnl = sum(r["profit_per_share"] for r in rows)
    wins = sum(1 for r in rows if _outcome_from_exit(r["side"], r["exit_type"], r["profit_per_share"]) == "WIN")
    print(f"win_rate = {wins}/{len(rows)} = {wins/len(rows)*100:.1f}%")
    print(f"total_pnl_per_share = {total_pnl:+.4f}")
    print(f"avg_pnl_per_share   = {total_pnl/len(rows):+.4f}")

    # By symbol
    by_sym = defaultdict(lambda: {"n": 0, "w": 0, "pnl": 0.0})
    for r in rows:
        b = by_sym[r["symbol"]]
        b["n"] += 1
        b["pnl"] += r["profit_per_share"]
        if _outcome_from_exit(r["side"], r["exit_type"], r["profit_per_share"]) == "WIN":
            b["w"] += 1
    print("\nby symbol:")
    for sym, b in sorted(by_sym.items()):
        print(f"  {sym}: n={b['n']:3d}  win%={b['w']/b['n']*100:5.1f}  pnl={b['pnl']:+.4f}  avg={b['pnl']/b['n']:+.4f}")

    # By window length (5m vs 15m) from contract_slug
    by_win = defaultdict(lambda: {"n": 0, "w": 0, "pnl": 0.0})
    for r in rows:
        m = SLUG_RE.match(r.get("contract_slug", ""))
        if not m:
            continue
        b = by_win[m.group(2)]
        b["n"] += 1
        b["pnl"] += r["profit_per_share"]
        if _outcome_from_exit(r["side"], r["exit_type"], r["profit_per_share"]) == "WIN":
            b["w"] += 1
    print("\nby window length:")
    for win, b in sorted(by_win.items()):
        if b["n"]:
            print(f"  {win:>3s}: n={b['n']:3d}  win%={b['w']/b['n']*100:5.1f}  pnl={b['pnl']:+.4f}  avg={b['pnl']/b['n']:+.4f}")

    # By exit_type
    by_et = defaultdict(int)
    for r in rows:
        by_et[r["exit_type"]] += 1
    print("\nby exit_type:")
    for et, n in sorted(by_et.items(), key=lambda kv: -kv[1]):
        print(f"  {et:<14s} {n}")

    # By side
    by_side = defaultdict(lambda: {"n": 0, "pnl": 0.0})
    for r in rows:
        b = by_side[r["side"]]
        b["n"] += 1
        b["pnl"] += r["profit_per_share"]
    print("\nby side:")
    for side, b in sorted(by_side.items()):
        print(f"  {side}: n={b['n']:3d}  pnl={b['pnl']:+.4f}  avg={b['pnl']/b['n']:+.4f}")


def _build_stream_index():
    """Map (symbol, ts_int) -> price by scanning bot.log STREAM lines."""
    idx = defaultdict(list)  # symbol -> list[(ts, price)]
    if not BOT_LOG.exists():
        return idx
    with open(BOT_LOG, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = STREAM_RE.search(line)
            if not m:
                continue
            sym, price, ts = m.group(1), float(m.group(2)), float(m.group(3))
            idx[sym].append((ts, price))
    for k in idx:
        idx[k].sort()
    return idx


def _nearest_price(stream, target_ts):
    if not stream:
        return None, None
    # binary search would be nicer; n is small enough.
    best = None
    best_dt = None
    for ts, p in stream:
        dt = abs(ts - target_ts)
        if best_dt is None or dt < best_dt:
            best, best_dt = (ts, p), dt
        if ts > target_ts + 60:
            break
    return best, best_dt


def audit_anchors():
    if not POSITIONS_JSON.exists():
        print("\n(no shadow_positions.json — nothing open)")
        return
    with open(POSITIONS_JSON) as f:
        try:
            positions = json.load(f)
        except Exception:
            print("\n(shadow_positions.json unreadable)")
            return
    if not positions:
        print("\n(no open positions)")
        return

    print(f"\n=== Window-anchor audit ({len(positions)} open positions) ===")
    streams = _build_stream_index()
    for pos_id, pos in positions.items():
        sym = pos.get("symbol")
        side = pos.get("side")
        slug = pos.get("contract_slug", "")
        wsp = pos.get("window_start_price")
        wet = pos.get("window_end_ts")
        m = SLUG_RE.match(slug)
        win_label = m.group(2) if m else "?"
        win_secs = 300 if win_label == "5m" else 900 if win_label == "15m" else None
        if not (wet and win_secs and sym):
            print(f"  {pos_id[:10]} {sym} {side} slug={slug} → missing fields, skip")
            continue
        wst = int(wet) - win_secs  # window_start_ts
        nearest, dt = _nearest_price(streams.get(sym, []), wst)
        if nearest is None:
            ref = "n/a"
            diff = "n/a"
        else:
            ref_price = nearest[1]
            ref = f"{ref_price:.4f} (Δt={dt:.1f}s)"
            try:
                diff = f"{(float(wsp) - ref_price):+.4f}"
            except Exception:
                diff = "n/a"
        print(
            f"  {win_label} {sym} {side} | stored_wsp={wsp} | "
            f"chainlink_at_wst={ref} | diff={diff} | slug={slug}"
        )


if __name__ == "__main__":
    summarize_exits()
    audit_anchors()
