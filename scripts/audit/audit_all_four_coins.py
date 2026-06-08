"""Combine archive (execution_log.archive.csv) + recent bot.log FINAL TRADEs.

Resolves all settlements via Gamma API and reports per-symbol W/L/EV.
Dedupes by (symbol, slug) so the same window isn't double-counted.
"""
import csv
import json
import re
import time
import requests
from collections import defaultdict
from datetime import datetime

ARCHIVE = "logs/execution_log.archive.csv"
BOT_LOG = "logs/bot.log"
GAMMA = "https://gamma-api.polymarket.com/events?slug={}"
VALID = {"BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD"}
SYM_PREFIX = {"BTCUSD": "btc", "ETHUSD": "eth", "SOLUSD": "sol", "XRPUSD": "xrp"}

# Polymarket UpDown payout structure (entry ~0.70, win pays 1.0)
WIN_PROFIT = 0.27   # avg net profit per win (cents per contract)
LOSS = -0.71        # net loss per loss


def from_archive():
    out = []
    with open(ARCHIVE, encoding="utf-8") as f:
        rdr = csv.reader(f)
        next(rdr, None)
        for parts in rdr:
            if len(parts) < 4:
                continue
            ts, sym, side, slug = parts[0], parts[1], parts[2], parts[3]
            if sym not in VALID or "-updown-15m-" not in slug:
                continue
            try:
                ts_f = float(ts)
            except ValueError:
                continue
            out.append({"ts": ts_f, "symbol": sym, "side": side, "slug": slug, "src": "archive"})
    return out


FINAL_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) ET \[INFO\] polyou_bot: FINAL TRADE \| symbol=(\w+) side=(\w+)"
)
DECISION_RE = re.compile(r"\[DECISION EMAIL SENT\] (\w+) \| (\w+) \| window_end_ts=(\d+)")


def from_botlog():
    out = []
    with open(BOT_LOG, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        m = FINAL_RE.match(line)
        if not m:
            continue
        ts_et, sym, side = m.group(1), m.group(2), m.group(3)
        if sym not in VALID:
            continue
        slug = None
        for j in range(i + 1, min(i + 80, len(lines))):
            dm = DECISION_RE.search(lines[j])
            if dm and dm.group(1) == sym and dm.group(2) == side:
                window_start = int(dm.group(3)) - 900
                slug = f"{SYM_PREFIX[sym]}-updown-15m-{window_start}"
                break
            if FINAL_RE.match(lines[j]):
                break
        if not slug:
            continue
        ts_f = datetime.strptime(ts_et, "%Y-%m-%d %H:%M:%S").timestamp()
        out.append({"ts": ts_f, "symbol": sym, "side": side, "slug": slug, "src": "botlog"})
    return out


def resolve(slug, cache):
    if slug in cache:
        return cache[slug]
    try:
        r = requests.get(GAMMA.format(slug), timeout=10)
        data = r.json()
        if not data:
            cache[slug] = (None, "no_event"); return cache[slug]
        m = data[0]["markets"][0]
    except Exception:
        cache[slug] = (None, "err"); return cache[slug]
    if not m.get("closed", False):
        cache[slug] = (None, "open"); return cache[slug]
    outs = m.get("outcomes", [])
    pr = m.get("outcomePrices", [])
    if isinstance(outs, str):
        try: outs = json.loads(outs)
        except: pass
    if isinstance(pr, str):
        try: pr = json.loads(pr)
        except: pass
    for i, p in enumerate(pr):
        if str(p) == "1":
            cache[slug] = (outs[i].upper(), "closed"); return cache[slug]
    cache[slug] = (None, "no_winner"); return cache[slug]


def wilson_low(wins, n, z=1.96):
    if n == 0:
        return 0.0
    p = wins / n
    denom = 1 + z*z/n
    centre = p + z*z/(2*n)
    half = z * ((p*(1-p)/n + z*z/(4*n*n)) ** 0.5)
    return (centre - half) / denom


def main():
    rows = from_archive() + from_botlog()
    seen = {}
    for r in rows:
        key = (r["symbol"], r["slug"])
        # prefer archive entry for stability
        if key not in seen or seen[key]["src"] != "archive":
            seen[key] = r
    rows = sorted(seen.values(), key=lambda r: r["ts"])
    print(f"Total unique trades: {len(rows)}")
    print(f"Date range: {datetime.fromtimestamp(rows[0]['ts'])} -> {datetime.fromtimestamp(rows[-1]['ts'])}\n")

    cache = {}
    per = defaultdict(lambda: {"w":0,"l":0,"open":0,"err":0})
    for i, r in enumerate(rows, 1):
        winner, status = resolve(r["slug"], cache)
        time.sleep(0.10)
        if status == "open":
            per[r["symbol"]]["open"] += 1
        elif winner is None:
            per[r["symbol"]]["err"] += 1
        else:
            per[r["symbol"]]["w" if winner == r["side"] else "l"] += 1
        if i % 30 == 0:
            print(f"  ... {i}/{len(rows)}")

    print("\n=== ALL FOUR COINS — combined archive + recent ===")
    print(f"{'SYM':6}  {'W':>4}  {'L':>4}  {'n':>4}  {'WR%':>6}  {'EV/trade':>10}  {'95% CI low WR':>14}  open  err")
    rank = []
    for sym in sorted(per):
        d = per[sym]
        n = d["w"] + d["l"]
        wr = d["w"]/n*100 if n else 0
        ev = (d["w"]*WIN_PROFIT + d["l"]*LOSS)/n if n else 0
        wlow = wilson_low(d["w"], n) * 100 if n else 0
        rank.append((sym, n, wr, ev, wlow, d))
        print(f"{sym:6}  {d['w']:>4}  {d['l']:>4}  {n:>4}  {wr:>5.1f}%  {ev:>+9.3f}$  {wlow:>13.1f}%  {d['open']:>4}  {d['err']:>3}")

    # break-even WR with 0.70 entry / 1.0 win, 0.71 loss: p*0.27 - (1-p)*0.71 > 0 -> p > 0.71/0.98 ≈ 72.4%
    breakeven = 0.71/(0.71+0.27) * 100
    print(f"\nBreak-even WR ≈ {breakeven:.1f}% (entry ~0.70, win pays ~1.00)")
    print("Wilson 95% CI lower bound = conservative estimate of true WR.")

    print("\n=== Ranked by EV ===")
    for sym, n, wr, ev, wlow, d in sorted(rank, key=lambda x: -x[3]):
        verdict = "PROFITABLE" if ev > 0 else "LOSING"
        ci_verdict = "ABOVE BE" if wlow >= breakeven else "below BE"
        print(f"  {sym}  EV={ev:+.3f}$/trade  WR={wr:.1f}% (n={n})  CI_low={wlow:.1f}% [{ci_verdict}]  -> {verdict}")


if __name__ == "__main__":
    main()
