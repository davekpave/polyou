"""Compute EV/$ of buying the favorite at its ask in last N seconds, by mid bucket."""
import csv, glob, ast
from collections import defaultdict
from bisect import bisect_left

gw_map = {r["slug"]: r["gamma_winner"]
          for r in csv.DictReader(open("cache/trades/_meta_gamma_winners.csv"))}
META = list(csv.DictReader(open("cache/trades/_meta.csv")))

print("Loading...")
book = defaultdict(list)
for path in sorted(glob.glob("logs/book_snapshots_2026*.csv")):
    for row in csv.DictReader(open(path, encoding="utf-8")):
        try:
            ts = float(row["ts_epoch"])
            bb = float(row["best_bid"]) if row["best_bid"] else None
            ba = float(row["best_ask"]) if row["best_ask"] else None
            ba_sz = float(row["best_ask_size"]) if row["best_ask_size"] else 0.0
        except Exception:
            continue
        book[row["token_id"]].append((ts, bb, ba, ba_sz))
for tok in book: book[tok].sort(key=lambda x: x[0])

def nearest(tok, target_ts, max_lookback=60):
    arr = book.get(tok)
    if not arr: return None
    times = [x[0] for x in arr]
    i = bisect_left(times, target_ts)
    cands = []
    if i < len(arr): cands.append(arr[i])
    if i > 0: cands.append(arr[i-1])
    best, bdt = None, None
    for v in cands:
        dt = abs(v[0] - target_ts)
        if dt > max_lookback: continue
        if best is None or dt < bdt:
            best, bdt = v, dt
    return best

for lead_s in (60, 30, 15):
    print(f"\n=== Buy favorite at ASK, {lead_s}s before window_end ===")
    # Bucket by ask price
    buckets = defaultdict(lambda: {"n":0,"wins":0,"cost":0.0,"payoff":0.0,"sizes":[]})
    skipped_wide = 0
    for r in META:
        slug = r["slug"]; winner = gw_map.get(slug)
        if not winner: continue
        toks = r["tokens"].split(",")
        if len(toks) != 2: continue
        try: ws = int(slug.rsplit("-",1)[1])
        except: continue
        target = ws + 900 - lead_s
        snaps = {}
        ok = True
        for tok in toks:
            s = nearest(tok, target)
            if s is None or s[1] is None or s[2] is None: ok=False; break
            snaps[tok] = s
        if not ok: continue
        # Favorite by mid
        fav_tok = max(snaps, key=lambda t: (snaps[t][1]+snaps[t][2])/2)
        bb, ba, ba_sz = snaps[fav_tok][1], snaps[fav_tok][2], snaps[fav_tok][3]
        if ba <= 0 or ba >= 1.0: continue
        spread = ba - bb
        if spread > 0.05:  # wide spread = unreliable
            skipped_wide += 1; continue

        # Bucket by ask
        if ba < 0.60: bkey = "<0.60"
        elif ba < 0.70: bkey = "0.60-0.70"
        elif ba < 0.80: bkey = "0.70-0.80"
        elif ba < 0.90: bkey = "0.80-0.90"
        elif ba < 0.95: bkey = "0.90-0.95"
        else: bkey = ">=0.95"

        b = buckets[bkey]
        b["n"] += 1
        won = (fav_tok == winner)
        if won:
            b["wins"] += 1
            b["payoff"] += 1.0  # per share
        b["cost"] += ba
        b["sizes"].append(ba_sz)

    order = ["<0.60","0.60-0.70","0.70-0.80","0.80-0.90","0.90-0.95",">=0.95"]
    print(f"  (skipped {skipped_wide} wide-spread markets)")
    print(f"  {'bucket':<12} {'n':>4} {'win%':>6} {'avg_ask':>8} {'EV/$':>8} {'avg_ask_sz':>10}")
    tot_n=tot_w=0; tot_c=tot_p=0.0
    for k in order:
        if k not in buckets: continue
        b = buckets[k]
        avg_ask = b["cost"]/b["n"]
        ev = (b["payoff"]-b["cost"])/b["cost"] if b["cost"] else 0
        avg_sz = sum(b["sizes"])/len(b["sizes"]) if b["sizes"] else 0
        win_pct = 100*b["wins"]/b["n"]
        print(f"  {k:<12} {b['n']:>4} {win_pct:>5.1f}% {avg_ask:>8.3f} {ev*100:>+7.1f}% {avg_sz:>10.1f}")
        tot_n+=b["n"]; tot_w+=b["wins"]; tot_c+=b["cost"]; tot_p+=b["payoff"]
    if tot_c:
        print(f"  {'TOTAL':<12} {tot_n:>4} {100*tot_w/tot_n:>5.1f}% {tot_c/tot_n:>8.3f} {(tot_p-tot_c)/tot_c*100:>+7.1f}%")
