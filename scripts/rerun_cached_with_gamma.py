"""Re-resolve all 151 cached markets via gamma, then re-run the queue-aware sim.
If EV/$ flips negative, the cached '_meta.winner_token' was wrong and the edge was fake."""
import csv, json, urllib.request, time, ast, glob
from collections import defaultdict
from bisect import bisect_left
import os

META = list(csv.DictReader(open("cache/trades/_meta.csv")))
print(f"Cached markets: {len(META)}")

CACHE_OUT = "cache/trades/_meta_gamma_winners.csv"
gamma_winners = {}
if os.path.exists(CACHE_OUT):
    for r in csv.DictReader(open(CACHE_OUT)):
        gamma_winners[r["slug"]] = r["gamma_winner"]
    print(f"Loaded cached gamma winners: {len(gamma_winners)}")

if len(gamma_winners) < len(META):
    print("Fetching gamma resolutions...")
    for i, r in enumerate(META):
        slug = r["slug"]
        if slug in gamma_winners: continue
        try:
            req = urllib.request.Request(f"https://gamma-api.polymarket.com/events/slug/{slug}",
                                          headers={"User-Agent": "Mozilla/5.0"})
            d = json.loads(urllib.request.urlopen(req, timeout=10).read())
            m = d["markets"][0]
            toks = m.get("clobTokenIds")
            if isinstance(toks, str): toks = json.loads(toks)
            op = m.get("outcomePrices")
            if isinstance(op, str): op = json.loads(op)
            yes_p, no_p = float(op[0]), float(op[1])
            winner = toks[0] if yes_p > no_p else (toks[1] if no_p > yes_p else "")
            gamma_winners[slug] = winner
        except Exception as e:
            gamma_winners[slug] = ""
        if (i+1) % 25 == 0:
            print(f"  {i+1}/{len(META)}")
        time.sleep(0.05)
    with open(CACHE_OUT, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["slug","gamma_winner"])
        for k,v in gamma_winners.items(): w.writerow([k,v])

# Compare cache vs gamma
disagree = same = missing = 0
for r in META:
    cw = r.get("winner_token","")
    gw = gamma_winners.get(r["slug"],"")
    if not gw: missing += 1
    elif cw == gw: same += 1
    else: disagree += 1
print(f"\nCached vs Gamma: same={same}  disagree={disagree}  gamma_missing={missing}")

# Build markets list using GAMMA winners
markets = []
for r in META:
    gw = gamma_winners.get(r["slug"], "")
    if not gw: continue
    try:
        toks = json.loads(r["tokens"]) if r["tokens"].startswith("[") else r["tokens"].split(",")
    except Exception:
        toks = r["tokens"].split(",")
    if gw not in toks: continue
    try:
        ws = int(r["slug"].rsplit("-",1)[1])
    except Exception:
        continue
    path = f"cache/trades/{r['slug']}.json"
    if not os.path.exists(path): continue
    trades = json.load(open(path))
    markets.append({"slug": r["slug"], "ws": ws, "we": ws+900, "winner": gw, "trades": trades, "tokens": toks})

print(f"Usable markets: {len(markets)}")

# Load book
print("Loading snapshots...")
book_index = defaultdict(list)
for path in sorted(glob.glob("logs/book_snapshots_2026*.csv")):
    for row in csv.DictReader(open(path, encoding="utf-8")):
        try: ts = float(row["ts_epoch"])
        except: continue
        try: bids = ast.literal_eval(row.get("top5_bids","")) if row.get("top5_bids") else []
        except: bids = []
        book_index[row["token_id"]].append((ts, bids))
for tok in book_index: book_index[tok].sort(key=lambda x: x[0])
print(f"  {len(book_index)} tokens")


def nearest_bids(tok, target_ts, max_lookback_s=120):
    arr = book_index.get(tok)
    if not arr: return None
    times = [x[0] for x in arr]
    i = bisect_left(times, target_ts)
    cands = []
    if i < len(arr): cands.append(arr[i])
    if i > 0: cands.append(arr[i-1])
    best, bdt = None, None
    for ts, bids in cands:
        dt = abs(ts - target_ts)
        if dt > max_lookback_s: continue
        if best is None or dt < bdt:
            best, bdt = bids, dt
    return best


def simulate(subset, bid_px=0.20, size_usdc=100.0, post_delay=30):
    win_cost = lose_cost = win_shares = 0.0
    n_filled = n_with_book = 0
    for m in subset:
        ws, we, winner, trades, tokens = m["ws"], m["we"], m["winner"], m["trades"], m["tokens"]
        if not trades: continue
        t_post = ws + post_delay
        had_book = had_fill = False
        for tok in tokens:
            bids = nearest_bids(tok, t_post)
            if bids is None: continue
            had_book = True
            bids_above = sum(sz for px,sz in bids if px > bid_px+1e-9)
            queue_at = sum(sz for px,sz in bids if abs(px-bid_px)<=1e-9)
            our_remaining = size_usdc/bid_px
            cost = filled = 0.0
            sells = sorted(
                (t for t in trades
                 if t.get("side")=="SELL"
                 and str(t.get("asset",""))==tok
                 and t_post <= int(t.get("timestamp",0)) < we
                 and float(t.get("price",1)) <= bid_px+1e-9),
                key=lambda x: int(x["timestamp"]))
            for s in sells:
                avail = float(s["size"])
                eat = min(avail, bids_above); bids_above -= eat; avail -= eat
                if avail<=0: continue
                eat = min(avail, queue_at); queue_at -= eat; avail -= eat
                if avail<=0: continue
                ours = min(avail, our_remaining)
                our_remaining -= ours
                filled += ours
                cost += ours*bid_px
                if our_remaining<=0: break
            if filled>0:
                had_fill=True
                if tok==winner: win_shares+=filled; win_cost+=cost
                else: lose_cost+=cost
        if had_book: n_with_book+=1
        if had_fill: n_filled+=1
    cost = win_cost+lose_cost
    pnl = win_shares-cost
    return {"n":len(subset),"book":n_with_book,"fill":n_filled,"cost":cost,"pnl":pnl,
            "ev": pnl/cost if cost else 0, "win$": win_cost/cost if cost else 0}


for bid in (0.20, 0.30):
    r = simulate(markets, bid_px=bid)
    print(f"\nbid={bid}  n={r['n']} book={r['book']} fill={r['fill']}  "
          f"cost=${r['cost']:,.0f} pnl=${r['pnl']:+,.0f}  EV/$={r['ev']*100:+.1f}%  win$={r['win$']*100:.1f}%")
