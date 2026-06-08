"""Live PnL audit v2 — dedupe exit_log to one closure per token_id.

Logic:
- Group exit_log rows by token_id.
- Verify all rows for a given token are identical (same entry/exit/type) → confirms re-logging.
- Take ONE row per token as the canonical closure.
- Compute realized win%, EV/$, totals — overall, by symbol, by exit_type, by time.
- Use $1 invested per trade. per-dollar return = (exit-entry)/entry.

Read-only.
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
BOT_LOG = ROOT / "logs" / "bot.log"


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_token_to_symbol():
    m = {}
    if EXEC_LOG.exists():
        with EXEC_LOG.open("r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                tid = row.get("token_id")
                sym = row.get("symbol")
                if tid and sym:
                    m[tid] = sym
    if BOT_LOG.exists():
        try:
            content = BOT_LOG.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            content = ""
        slug_sym = {"btc": "BTCUSD", "eth": "ETHUSD",
                    "sol": "SOLUSD", "xrp": "XRPUSD"}
        for match in re.finditer(
                r"token_id=(\d+).{0,500}?(btc|eth|sol|xrp)-updown",
                content, flags=re.DOTALL | re.IGNORECASE):
            tid = match.group(1)
            sym = slug_sym[match.group(2).lower()]
            if tid not in m:
                m[tid] = sym
        # Reverse direction too
        for match in re.finditer(
                r"(btc|eth|sol|xrp)-updown.{0,500}?token_id=(\d+)",
                content, flags=re.DOTALL | re.IGNORECASE):
            tid = match.group(2)
            sym = slug_sym[match.group(1).lower()]
            if tid not in m:
                m[tid] = sym
    return m


def main():
    sym_map = build_token_to_symbol()

    raw = []
    with EXIT_LOG.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            raw.append(row)

    # Group by token, take FIRST closure
    groups = defaultdict(list)
    for r in raw:
        groups[r["token_id"]].append(r)

    canonical = []
    inconsistent_tokens = 0
    for tid, rows in groups.items():
        rows.sort(key=lambda r: to_float(r.get("timestamp")) or 0)
        first = rows[0]
        # check all rows are identical
        for other in rows[1:]:
            if (other.get("entry_price") != first.get("entry_price")
                    or other.get("exit_price") != first.get("exit_price")
                    or other.get("type") != first.get("type")):
                inconsistent_tokens += 1
                break
        canonical.append(first)

    print(f"raw exit_log rows                : {len(raw)}")
    print(f"unique token_ids                 : {len(groups)}")
    print(f"tokens w/ varying re-log content : {inconsistent_tokens}")
    print(f"canonical closures (1 per token) : {len(canonical)}")
    print(f"token->symbol mappings           : {len(sym_map)}")
    if canonical:
        ts_vals = [to_float(r.get("timestamp")) for r in canonical
                   if to_float(r.get("timestamp"))]
        if ts_vals:
            t_lo = datetime.fromtimestamp(min(ts_vals), tz=timezone.utc)
            t_hi = datetime.fromtimestamp(max(ts_vals), tz=timezone.utc)
            days = (max(ts_vals) - min(ts_vals)) / 86400
            print(f"closure time range               : {t_lo}  ..  {t_hi}  ({days:.2f} days)")

    def evaluate(name, rows):
        valid = []
        for r in rows:
            ep = to_float(r.get("entry_price"))
            xp = to_float(r.get("exit_price"))
            if ep is None or xp is None or ep <= 0:
                continue
            valid.append((ep, xp, r))
        n = len(valid)
        if n == 0:
            print(f"  {name:42s}  n=0")
            return
        per_dollar = sum((xp - ep) / ep for ep, xp, _ in valid)
        wins = sum(1 for ep, xp, _ in valid if xp > ep)
        be = sum(1 for ep, xp, _ in valid if xp == ep)
        losses = n - wins - be
        mean_ep = sum(ep for ep, _, _ in valid) / n
        print(f"  {name:42s}  n={n:4d}  win={100*wins/n:5.1f}%  "
              f"loss={100*losses/n:5.1f}%  be={100*be/n:4.1f}%  "
              f"mean_entry={mean_ep:.3f}  EV/$={per_dollar/n:+.4f}  "
              f"total/$={per_dollar:+.3f}")

    print()
    print("=" * 96)
    print("DEDUPED REALIZED PnL — overall")
    print("=" * 96)
    evaluate("ALL canonical closures", canonical)

    print()
    print("By exit type:")
    by_type = defaultdict(list)
    for r in canonical:
        by_type[r.get("type", "?")].append(r)
    for t, rs in sorted(by_type.items(), key=lambda x: -len(x[1])):
        evaluate(f"  type={t}", rs)

    print()
    print("=" * 96)
    print("DEDUPED REALIZED PnL — by symbol")
    print("=" * 96)
    by_sym = defaultdict(list)
    unmapped = []
    for r in canonical:
        sym = sym_map.get(r["token_id"])
        if sym:
            by_sym[sym].append(r)
        else:
            unmapped.append(r)
    print(f"  unmapped closures (no symbol joined): {len(unmapped)}")
    if unmapped:
        evaluate("  UNMAPPED ALL", unmapped)
    for sym in sorted(by_sym):
        evaluate(f"{sym} ALL", by_sym[sym])
        sub = defaultdict(list)
        for r in by_sym[sym]:
            sub[r.get("type", "?")].append(r)
        for t, rs in sorted(sub.items(), key=lambda x: -len(x[1])):
            evaluate(f"  {sym} type={t}", rs)

    print()
    print("=" * 96)
    print("DEDUPED time stability (overall)")
    print("=" * 96)
    timed = sorted([r for r in canonical if to_float(r.get("timestamp"))],
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

    # Distribution of stop-losses by entry price
    print()
    print("=" * 96)
    print("STOP_LOSS distribution by entry price (deduped)")
    print("=" * 96)
    sl = [r for r in canonical if r.get("type") == "STOP_LOSS"]
    buckets = [(0.0, 0.5, "0.00-0.50"), (0.5, 0.7, "0.50-0.70"), (0.7, 0.8, "0.70-0.80"), (0.8, 0.9, "0.80-0.90"), (0.9, 1.01, "0.90-1.00")]
    for lo, hi, name in buckets:
        sub = [r for r in sl if (ep := to_float(r.get("entry_price"))) and lo <= ep < hi]
        if sub:
            evaluate(f"  STOP_LOSS entry {name}", sub)

    # Same for TAKE_PROFIT
    print()
    print("TAKE_PROFIT distribution by entry price (deduped)")
    tp = [r for r in canonical if r.get("type") == "TAKE_PROFIT"]
    for lo, hi, name in buckets:
        sub = [r for r in tp if (ep := to_float(r.get("entry_price"))) and lo <= ep < hi]
        if sub:
            evaluate(f"  TAKE_PROFIT entry {name}", sub)


if __name__ == "__main__":
    main()