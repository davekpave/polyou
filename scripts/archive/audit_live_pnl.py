"""Audit live trade logs:
- logs/exit_log.csv  : every position closure with realized profit_cents (per-share basis, like CSV)
- logs/execution_log.csv : every entry decision (has token_id -> symbol mapping)
- active_positions.json  : currently open

Joins exit_log to symbol via token_id (using execution_log + bot.log fallback).
Reports overall and per-symbol realized PnL, win%, and EV/$.

Read-only. Does not modify anything.
"""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
EXIT_LOG = ROOT / "logs" / "exit_log.csv"
EXEC_LOG = ROOT / "logs" / "execution_log.csv"
ACTIVE = ROOT / "active_positions.json"
BOT_LOG = ROOT / "logs" / "bot.log"


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_token_to_symbol():
    """Map token_id -> symbol from execution_log.csv (and bot.log as fallback)."""
    m = {}
    if EXEC_LOG.exists():
        with EXEC_LOG.open("r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                tid = row.get("token_id")
                sym = row.get("symbol")
                if tid and sym:
                    m[tid] = sym
    # Fallback: scrape bot.log for "token_id=<long> ... symbol=<X>" near each other
    if BOT_LOG.exists():
        # Build a quick regex pass; cheap because only ~MB-scale log
        try:
            content = BOT_LOG.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            content = ""
        # Scan for slug -> symbol patterns
        for match in re.finditer(
                r"token_id=(\d+).{0,400}?symbol=(\w+)|symbol=(\w+).{0,400}?token_id=(\d+)",
                content, flags=re.DOTALL):
            tid = match.group(1) or match.group(4)
            sym = match.group(2) or match.group(3)
            if tid and sym and tid not in m:
                m[tid] = sym
        # Also scrape contract_slug like "btc-updown-15m-..." -> BTCUSD
        # Build slug -> symbol via "btc"/"eth"/"sol"/"xrp"
        slug_sym = {"btc": "BTCUSD", "eth": "ETHUSD",
                    "sol": "SOLUSD", "xrp": "XRPUSD"}
        for match in re.finditer(
                r"token_id=(\d+).{0,400}?(btc|eth|sol|xrp)-updown",
                content, flags=re.DOTALL | re.IGNORECASE):
            tid = match.group(1)
            sym = slug_sym[match.group(2).lower()]
            if tid not in m:
                m[tid] = sym
    return m


def main():
    sym_map = build_token_to_symbol()
    print(f"token->symbol mappings discovered: {len(sym_map)}")

    # Load exit log
    exits = []
    with EXIT_LOG.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            exits.append(row)
    print(f"exit_log rows: {len(exits)}")

    # Active positions
    if ACTIVE.exists():
        try:
            ap = json.loads(ACTIVE.read_text(encoding="utf-8"))
            print(f"active_positions: {len(ap) if hasattr(ap,'__len__') else 'n/a'}")
        except Exception as e:
            print(f"active_positions parse error: {e}")

    # Time range
    ts_vals = [to_float(r.get("timestamp")) for r in exits if to_float(r.get("timestamp"))]
    if ts_vals:
        t_lo = datetime.fromtimestamp(min(ts_vals), tz=timezone.utc)
        t_hi = datetime.fromtimestamp(max(ts_vals), tz=timezone.utc)
        days = (max(ts_vals) - min(ts_vals)) / 86400
        print(f"exit_log time range: {t_lo}  ..  {t_hi}  ({days:.2f} days)")

    # Exit-type breakdown
    print()
    print("Exit-type breakdown:")
    by_type = defaultdict(list)
    for r in exits:
        by_type[r.get("type", "?")].append(r)
    for t, rs in sorted(by_type.items(), key=lambda x: -len(x[1])):
        print(f"  {t:20s}  n={len(rs):4d}")

    # Compute true per-dollar PnL
    # profit_cents in CSV = exit_price - entry_price (per-share). To convert to per-dollar:
    #   per_dollar_return = (exit_price - entry_price) / entry_price
    print()
    print("=" * 96)
    print("REALIZED PnL — overall")
    print("=" * 96)

    def evaluate(name, rows):
        valid = []
        for r in rows:
            ep = to_float(r.get("entry_price"))
            xp = to_float(r.get("exit_price"))
            if ep is None or xp is None or ep <= 0:
                continue
            valid.append((ep, xp))
        n = len(valid)
        if n == 0:
            print(f"  {name:40s}  n=0")
            return
        per_share = sum(xp - ep for ep, xp in valid)
        per_dollar = sum((xp - ep) / ep for ep, xp in valid)
        wins = sum(1 for ep, xp in valid if xp > ep)
        breakevens = sum(1 for ep, xp in valid if xp == ep)
        losses = n - wins - breakevens
        mean_ep = sum(ep for ep, _ in valid) / n
        # Assume $1 per trade
        print(f"  {name:40s}  n={n:4d}  win={100*wins/n:5.1f}%  "
              f"loss={100*losses/n:5.1f}%  be={100*breakevens/n:4.1f}%  "
              f"mean_entry={mean_ep:.3f}  EV/$={per_dollar/n:+.4f}  "
              f"sum_per_share={per_share:+.2f}c  sum_per_$={per_dollar:+.3f}")

    evaluate("ALL exits", exits)

    # Exclude STOP_LOSS / forced exits from the "fair-vs-strategy" view
    print()
    print("Per exit-type:")
    for t, rs in sorted(by_type.items(), key=lambda x: -len(x[1])):
        evaluate(f"  type={t}", rs)

    # By symbol
    print()
    print("=" * 96)
    print("REALIZED PnL — by symbol (joined via token_id -> execution_log/bot.log)")
    print("=" * 96)
    by_sym = defaultdict(list)
    unmapped = []
    for r in exits:
        tid = r.get("token_id")
        sym = sym_map.get(tid)
        if sym:
            by_sym[sym].append(r)
        else:
            unmapped.append(r)
    print(f"  unmapped exits (no symbol found): {len(unmapped)}")
    for sym in sorted(by_sym):
        evaluate(f"{sym} ALL", by_sym[sym])
        # And split by exit type
        sub_by_type = defaultdict(list)
        for r in by_sym[sym]:
            sub_by_type[r.get("type", "?")].append(r)
        for t, rs in sorted(sub_by_type.items(), key=lambda x: -len(x[1])):
            evaluate(f"  {sym} type={t}", rs)

    # Time stability — split chronologically
    print()
    print("=" * 96)
    print("Time stability (overall, all exit types) — halves & quartiles")
    print("=" * 96)
    timed = sorted([r for r in exits if to_float(r.get("timestamp"))],
                   key=lambda r: to_float(r["timestamp"]))
    h = len(timed) // 2
    evaluate("FIRST half", timed[:h])
    evaluate("SECOND half", timed[h:])
    print()
    q = len(timed) // 4
    for i in range(4):
        chunk = timed[i*q:(i+1)*q] if i < 3 else timed[i*q:]
        if chunk:
            t0 = datetime.fromtimestamp(to_float(chunk[0]["timestamp"]), tz=timezone.utc)
            t1 = datetime.fromtimestamp(to_float(chunk[-1]["timestamp"]), tz=timezone.utc)
            evaluate(f"Q{i+1} ({t0:%m-%d %H:%M} .. {t1:%m-%d %H:%M})", chunk)

    # Same-token-id duplicates check (do we have multiple closures per position?)
    print()
    print("=" * 96)
    print("Duplicate closures per token_id (same position closed multiple times?)")
    print("=" * 96)
    by_tid = defaultdict(list)
    for r in exits:
        by_tid[r.get("token_id")].append(r)
    dup_counts = sorted([(len(v), tid) for tid, v in by_tid.items()], reverse=True)
    print(f"  unique token_ids in exit_log: {len(by_tid)}")
    print(f"  exits per token_id (top 10):")
    for cnt, tid in dup_counts[:10]:
        print(f"    {tid[:30]}...  exits={cnt}")
    multi = sum(1 for c, _ in dup_counts if c > 1)
    print(f"  token_ids with >1 exit row: {multi}")


if __name__ == "__main__":
    main()
