"""Audit BTC vs ETH outcomes by parsing bot.log FINAL TRADE entries.

For each FINAL TRADE we look ahead a few lines for the matching DECISION EMAIL SENT
to derive the contract slug (window_end_ts - 900 = window_start). Then we resolve
the actual settlement via Polymarket Gamma API.
"""
import re
import time
import json
import requests
from collections import defaultdict
from datetime import datetime

BOT_LOG = "logs/bot.log"
GAMMA = "https://gamma-api.polymarket.com/events?slug={}"

SYM_TO_PREFIX = {"BTCUSD": "btc", "ETHUSD": "eth", "SOLUSD": "sol", "XRPUSD": "xrp"}

FINAL_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) ET \[INFO\] polyou_bot: FINAL TRADE \| "
    r"symbol=(\w+) side=(\w+)"
)
DECISION_RE = re.compile(
    r"\[DECISION EMAIL SENT\] (\w+) \| (\w+) \| window_end_ts=(\d+)"
)


def parse_log():
    """Return list of dicts: ts(ET str), symbol, side, slug (or None)."""
    trades = []
    with open(BOT_LOG, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        m = FINAL_RE.match(line)
        if not m:
            continue
        ts_et, sym, side = m.group(1), m.group(2), m.group(3)
        # look ahead up to 60 lines for matching decision email
        slug = None
        for j in range(i + 1, min(i + 80, len(lines))):
            dm = DECISION_RE.search(lines[j])
            if dm and dm.group(1) == sym and dm.group(2) == side:
                window_start = int(dm.group(3)) - 900
                prefix = SYM_TO_PREFIX.get(sym, sym.lower())
                slug = f"{prefix}-updown-15m-{window_start}"
                break
            # stop scanning if we hit another FINAL TRADE
            if FINAL_RE.match(lines[j]):
                break
        trades.append({"ts_et": ts_et, "symbol": sym, "side": side, "slug": slug})
    return trades


def resolve(slug, cache):
    if slug in cache:
        return cache[slug]
    try:
        r = requests.get(GAMMA.format(slug), timeout=10)
        data = r.json()
        if not data:
            cache[slug] = (None, "no_event")
            return cache[slug]
        m = data[0]["markets"][0]
    except Exception as e:
        cache[slug] = (None, f"err:{e}")
        return cache[slug]
    closed = m.get("closed", False)
    if not closed:
        cache[slug] = (None, "open")
        return cache[slug]
    outcomes = m.get("outcomes", [])
    prices = m.get("outcomePrices", [])
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except Exception:
            pass
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except Exception:
            pass
    for i, p in enumerate(prices):
        if str(p) == "1":
            cache[slug] = (outcomes[i].upper(), "closed")
            return cache[slug]
    cache[slug] = (None, "closed_no_winner")
    return cache[slug]


def to_unix(ts_et):
    # bot logs in ET; we just want a comparable number for cutoff (approx, ET vs UTC offset is fine for relative compare)
    # use naive datetime epoch (treat as UTC) — only used for cutoff comparison with another ET-based cutoff string
    return datetime.strptime(ts_et, "%Y-%m-%d %H:%M:%S").timestamp()


CUTOFF_48H_ET = "2026-04-27 08:15:00"


def main():
    trades = parse_log()
    print(f"Parsed {len(trades)} FINAL TRADE entries from bot.log\n")

    cache = {}
    per_sym_all = defaultdict(lambda: {"w": 0, "l": 0, "open": 0, "err": 0, "noslug": 0})
    per_sym_48h = defaultdict(lambda: {"w": 0, "l": 0, "open": 0, "err": 0, "noslug": 0})
    cutoff = to_unix(CUTOFF_48H_ET)

    rows = []
    for t in trades:
        in48 = to_unix(t["ts_et"]) >= cutoff
        if not t["slug"]:
            outcome = "NO_SLUG"
            per_sym_all[t["symbol"]]["noslug"] += 1
            if in48:
                per_sym_48h[t["symbol"]]["noslug"] += 1
            rows.append((t["ts_et"], t["symbol"], t["side"], "-", "-", outcome))
            continue
        winner, status = resolve(t["slug"], cache)
        time.sleep(0.12)
        if status == "open":
            outcome = "PENDING"
            per_sym_all[t["symbol"]]["open"] += 1
            if in48:
                per_sym_48h[t["symbol"]]["open"] += 1
        elif winner is None:
            outcome = f"ERR({status})"
            per_sym_all[t["symbol"]]["err"] += 1
            if in48:
                per_sym_48h[t["symbol"]]["err"] += 1
        else:
            won = winner == t["side"]
            outcome = "WIN" if won else "LOSS"
            key = "w" if won else "l"
            per_sym_all[t["symbol"]][key] += 1
            if in48:
                per_sym_48h[t["symbol"]][key] += 1
        rows.append((t["ts_et"], t["symbol"], t["side"], t["slug"], winner or "-", outcome))

    print(f"{'TIMESTAMP (ET)':19}  {'SYM':6}  {'SIDE':4}  {'SLUG':38}  {'WIN':6}  OUTCOME")
    for r in rows:
        print(f"{r[0]:19}  {r[1]:6}  {r[2]:4}  {r[3]:38}  {r[4]:6}  {r[5]}")

    def show(label, d):
        decided = d["w"] + d["l"]
        wr = (d["w"] / decided * 100) if decided else 0.0
        print(f"  {label:8}  W={d['w']}  L={d['l']}  open={d['open']}  err={d['err']}  noslug={d['noslug']}  WR={wr:.1f}% (n={decided})")

    print("\n=== LIFETIME (per symbol) ===")
    for sym in sorted(per_sym_all):
        show(sym, per_sym_all[sym])

    print(f"\n=== LAST 48h (since {CUTOFF_48H_ET} ET) ===")
    for sym in sorted(per_sym_48h):
        show(sym, per_sym_48h[sym])


if __name__ == "__main__":
    main()
