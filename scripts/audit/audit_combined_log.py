"""Audit per-symbol settlements for the canonical combined log."""
import csv, json, time, requests
from collections import defaultdict
from datetime import datetime

COMBINED = "logs/execution_log.combined.csv"
GAMMA = "https://gamma-api.polymarket.com/events?slug={}"
WIN_PROFIT, LOSS = 0.27, -0.71

def resolve(slug, cache):
    if slug in cache: return cache[slug]
    try:
        m = requests.get(GAMMA.format(slug), timeout=10).json()[0]["markets"][0]
    except Exception:
        cache[slug] = (None, "err"); return cache[slug]
    if not m.get("closed", False):
        cache[slug] = (None, "open"); return cache[slug]
    outs, pr = m.get("outcomes", []), m.get("outcomePrices", [])
    if isinstance(outs, str): outs = json.loads(outs)
    if isinstance(pr, str): pr = json.loads(pr)
    for i, p in enumerate(pr):
        if str(p) == "1":
            cache[slug] = (outs[i].upper(), "closed"); return cache[slug]
    cache[slug] = (None, "no_winner"); return cache[slug]

def wilson_low(w, n, z=1.96):
    if not n: return 0.0
    p = w/n
    d = 1 + z*z/n
    c = p + z*z/(2*n)
    h = z * ((p*(1-p)/n + z*z/(4*n*n))**0.5)
    return (c - h)/d

def main():
    rows = []
    with open(COMBINED) as f:
        for r in csv.DictReader(f):
            rows.append(r)
    rows.sort(key=lambda r: float(r["timestamp"]))
    print(f"Total trades: {len(rows)}")
    print(f"Date range: {datetime.fromtimestamp(float(rows[0]['timestamp']))} -> {datetime.fromtimestamp(float(rows[-1]['timestamp']))}\n")

    cache = {}
    per = defaultdict(lambda: {"w":0,"l":0,"open":0,"err":0})
    for i, r in enumerate(rows, 1):
        winner, status = resolve(r["contract_slug"], cache)
        time.sleep(0.10)
        sym = r["symbol"]
        if status == "open":
            per[sym]["open"] += 1
        elif winner is None:
            per[sym]["err"] += 1
        else:
            per[sym]["w" if winner == r["side"] else "l"] += 1
        if i % 30 == 0:
            print(f"  ... {i}/{len(rows)}")

    print(f"\n=== COMBINED LOG ({COMBINED}) ===")
    print(f"{'SYM':6}  {'W':>4}  {'L':>4}  {'n':>4}  {'WR%':>6}  {'EV/trade':>10}  {'95% CI low':>10}  open  err")
    rank = []
    for sym in sorted(per):
        d = per[sym]
        n = d["w"] + d["l"]
        wr = d["w"]/n*100 if n else 0
        ev = (d["w"]*WIN_PROFIT + d["l"]*LOSS)/n if n else 0
        wlow = wilson_low(d["w"], n) * 100
        rank.append((sym, n, wr, ev, wlow))
        print(f"{sym:6}  {d['w']:>4}  {d['l']:>4}  {n:>4}  {wr:>5.1f}%  {ev:>+9.3f}$  {wlow:>9.1f}%  {d['open']:>4}  {d['err']:>3}")

    be = 0.71/(0.71+0.27) * 100
    print(f"\nBreak-even WR ≈ {be:.1f}%")
    print("\n=== Ranked by EV ===")
    for sym, n, wr, ev, wlow in sorted(rank, key=lambda x: -x[3]):
        verdict = "PROFITABLE" if ev > 0 else "LOSING"
        ci = "ABOVE BE" if wlow >= be else "below BE"
        print(f"  {sym}  EV={ev:+.3f}$  WR={wr:.1f}% (n={n})  CI_low={wlow:.1f}% [{ci}]  -> {verdict}")

if __name__ == "__main__":
    main()
