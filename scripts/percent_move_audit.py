import re, json, csv, sys, statistics, time, urllib.request, urllib.error
from collections import deque, defaultdict
from datetime import datetime, timedelta

LOG = r"c:\Users\Dave\polyou_4\logs\bot.log"
OUT = r"c:\Users\Dave\polyou_4\logs\percent_move_audit.csv"

TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
FINAL_RE = re.compile(r"FINAL TRADE \| symbol=(\w+) side=(\w+) priority=([\-0-9\.eE]+) quality=([\-0-9\.eE]+)")
DEC_RE = re.compile(r"\[DECISION EMAIL SENT\] (\w+) \| (\w+) \| window_end_ts=(\d+)")
KV_RE = re.compile(r"(\w+)=([\-0-9\.eE]+)")
KEYS = ["percent_move","dynamic_percent_threshold","volatility","slope_z","distance_z","vol_ratio","percent_vol_ratio"]

cutoff = datetime.now() - timedelta(days=7)

# Stream through file, keep ring buffer of last 60 lines
buf = deque(maxlen=60)
trades = []  # each: dict
pending = []  # FINAL TRADE awaiting DECISION EMAIL within next ~10 lines

# We'll do single pass: when FINAL TRADE found, capture context buffer; then look ahead for DECISION EMAIL
# Use a simple state: after a FINAL TRADE found, mark it open, scan up to 30 next lines for DECISION EMAIL with matching symbol/side.

open_trades = []  # list of (trade_dict, lines_remaining)

with open(LOG, "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        m_ts = TS_RE.match(line)
        if m_ts:
            try:
                ts = datetime.strptime(m_ts.group(1), "%Y-%m-%d %H:%M:%S")
            except:
                ts = None
        else:
            ts = None

        # Decrement lookahead counters; check DECISION EMAIL for open trades
        if open_trades:
            md = DEC_RE.search(line)
            if md:
                sym, side, wend = md.group(1), md.group(2), int(md.group(3))
                for t in list(open_trades):
                    if t["symbol"] == sym and t["side"] == side and t["window_end_ts"] is None:
                        t["window_end_ts"] = wend
                        open_trades.remove(t)
                        break
            # decrement
            for t in list(open_trades):
                t["lookahead"] -= 1
                if t["lookahead"] <= 0:
                    open_trades.remove(t)

        mf = FINAL_RE.search(line)
        if mf:
            sym, side, pri, qual = mf.group(1), mf.group(2), float(mf.group(3)), float(mf.group(4))
            # Filter by date
            if ts and ts < cutoff:
                buf.append(line)
                continue
            # Extract kv from buffer (last 60 lines)
            kv = {k: None for k in KEYS}
            for prev in buf:
                for km in KV_RE.finditer(prev):
                    k, v = km.group(1), km.group(2)
                    if k in kv and kv[k] is None:
                        try:
                            kv[k] = float(v)
                        except:
                            pass
            trade = {
                "ts": ts,
                "symbol": sym, "side": side,
                "priority": pri, "quality": qual,
                "window_end_ts": None,
                "lookahead": 30,
                **kv,
            }
            trades.append(trade)
            open_trades.append(trade)

        buf.append(line)

print(f"Found {len(trades)} FINAL TRADE entries in last 7 days", file=sys.stderr)

# Query Gamma for each unique slug
def fetch_gamma(slug):
    url = f"https://gamma-api.polymarket.com/events?slug={slug}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        if not data:
            return None
        ev = data[0]
        markets = ev.get("markets", [])
        if not markets:
            return None
        m = markets[0]
        if not m.get("closed"):
            return None
        outs = m.get("outcomes")
        prices = m.get("outcomePrices")
        if isinstance(outs, str): outs = json.loads(outs)
        if isinstance(prices, str): prices = json.loads(prices)
        winner = None
        for o, p in zip(outs, prices):
            if str(p) == "1" or float(p) >= 0.99:
                winner = o.upper()
                break
        return winner
    except Exception as e:
        return f"ERR:{e}"

slug_cache = {}
for t in trades:
    if t["window_end_ts"] is None:
        t["outcome"] = "NOSLUG"
        continue
    win_start = t["window_end_ts"] - 900
    raw = t["symbol"].lower(); sym = raw[:-3] if raw.endswith("usd") else raw
    slug = f"{sym}-updown-15m-{win_start}"
    t["slug"] = slug
    if slug not in slug_cache:
        slug_cache[slug] = fetch_gamma(slug)
        time.sleep(0.05)
    winner = slug_cache[slug]
    if winner is None:
        t["outcome"] = "UNSETTLED"
    elif isinstance(winner, str) and winner.startswith("ERR"):
        t["outcome"] = "UNSETTLED"
    else:
        t["outcome"] = "W" if winner == t["side"].upper() else "L"

# Write CSV
cols = ["ts_iso","symbol","side","outcome","priority","quality"] + KEYS
with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(cols)
    for t in trades:
        w.writerow([
            t["ts"].isoformat() if t["ts"] else "",
            t["symbol"], t["side"], t.get("outcome",""),
            t["priority"], t["quality"],
            *[t.get(k) for k in KEYS],
        ])

# Summary
def stats(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return {"n": len(vals), "mean": statistics.mean(vals), "median": statistics.median(vals),
            "min": min(vals), "max": max(vals)}

by_sym = defaultdict(list)
for t in trades:
    by_sym[t["symbol"]].append(t)

print("\n========= SUMMARY =========")
overall_W = sum(1 for t in trades if t["outcome"]=="W")
overall_L = sum(1 for t in trades if t["outcome"]=="L")
overall_U = sum(1 for t in trades if t["outcome"] in ("UNSETTLED","NOSLUG"))
print(f"Overall: W={overall_W} L={overall_L} Unsettled={overall_U} Total={len(trades)}")
if (overall_W+overall_L)>0:
    print(f"Overall WinRate: {overall_W/(overall_W+overall_L):.2%}")

for sym, ts in sorted(by_sym.items()):
    W = [t for t in ts if t["outcome"]=="W"]
    L = [t for t in ts if t["outcome"]=="L"]
    U = [t for t in ts if t["outcome"] in ("UNSETTLED","NOSLUG")]
    print(f"\n--- {sym}: W={len(W)} L={len(L)} Unsettled={len(U)} Total={len(ts)} ---")
    if (len(W)+len(L))>0:
        print(f"  WinRate: {len(W)/(len(W)+len(L)):.2%}")
    for k in KEYS:
        sW = stats([t.get(k) for t in W])
        sL = stats([t.get(k) for t in L])
        def f(s):
            if s is None: return "n/a"
            return f"n={s['n']} mean={s['mean']:.4f} med={s['median']:.4f} min={s['min']:.4f} max={s['max']:.4f}"
        print(f"  {k}:")
        print(f"    W: {f(sW)}")
        print(f"    L: {f(sL)}")

    # Blocking analysis on percent_move
    print(f"  Blocking analysis (percent_move vs dynamic_percent_threshold):")
    for mult in [2.0, 3.0, 4.0]:
        def blocked(group):
            cnt = 0; tot = 0
            for t in group:
                pm = t.get("percent_move")
                th = t.get("dynamic_percent_threshold")
                if pm is None or th is None: continue
                tot += 1
                if pm < th * mult:
                    cnt += 1
            return cnt, tot
        bW, tW = blocked(W); bL, tL = blocked(L)
        wf = f"{bW}/{tW} ({bW/tW:.1%})" if tW else "n/a"
        lf = f"{bL}/{tL} ({bL/tL:.1%})" if tL else "n/a"
        print(f"    {mult}x threshold -> blocked W: {wf} | blocked L: {lf}")

print(f"\nFull table written to: {OUT}")

