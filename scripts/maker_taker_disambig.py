"""
Disambiguate maker vs taker for cheap-buy trades in early windows.

Heuristic:
- Group trades by transactionHash.
- If a tx has multiple trades, the wallet that appears in ALL of them is the taker;
  the other wallets are makers.
- If a tx has only one trade, mark role='unknown'.

Then, for BUY trades in EARLY windows (0-50% of the 15m), price < 0.40,
report win-rate and EV/$ split by role (maker vs taker vs unknown).

If the +EV is concentrated in 'maker' rows, it's market-making P&L we can't take.
If it's also strong for 'taker' rows, taker-side execution is plausible.
"""
import csv, json, glob, os, collections

META = "cache/trades/_meta.csv"
TRADES_DIR = "cache/trades"

# Load market metadata
meta = {}
with open(META, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        slug = row["slug"]
        try:
            ws = int(slug.rsplit("-", 1)[1])
        except Exception:
            continue
        meta[slug] = {
            "winner_token": row.get("winner_token", "").strip(),
            "window_start": ws,
            "window_end": ws + 900,
        }

# Per-tx grouping across ALL trades (so we identify takers correctly)
# But we only care about cheap early BUYs. We still need full tx context to classify.
# Strategy: for each market file, group its trades by tx, classify, then filter.

cheap_rows = []  # list of (role, win, size, price, time_frac)

n_markets = 0
for path in glob.glob(os.path.join(TRADES_DIR, "*.json")):
    slug = os.path.splitext(os.path.basename(path))[0]
    if slug not in meta:
        continue
    m = meta[slug]
    if not m["winner_token"]:
        continue
    ws, we = m["window_start"], m["window_end"]
    winner = m["winner_token"]
    try:
        trades = json.load(open(path, encoding="utf-8"))
    except Exception:
        continue
    if not trades:
        continue
    n_markets += 1

    # Group by tx
    by_tx = collections.defaultdict(list)
    for t in trades:
        by_tx[t.get("transactionHash", "")].append(t)

    for txh, group in by_tx.items():
        if not txh:
            role_for = {id(t): "unknown" for t in group}
        elif len(group) == 1:
            role_for = {id(group[0]): "unknown"}
        else:
            # Find wallet present in ALL trades of this tx
            wallets = [t.get("proxyWallet", "").lower() for t in group]
            counts = collections.Counter(wallets)
            taker = None
            for w, c in counts.items():
                if c == len(group):
                    taker = w
                    break
            role_for = {}
            for t in group:
                w = t.get("proxyWallet", "").lower()
                if taker is not None and w == taker:
                    role_for[id(t)] = "taker"
                else:
                    role_for[id(t)] = "maker"

        for t in group:
            if t.get("side") != "BUY":
                continue
            try:
                price = float(t["price"])
                size = float(t["size"])
                ts = int(t["timestamp"])
            except Exception:
                continue
            if price >= 0.40:
                continue
            if ts < ws or ts >= we:
                continue
            tf = (ts - ws) / 900.0
            if tf >= 0.5:  # early window only
                continue
            asset = str(t.get("asset", ""))
            won = (asset == winner)
            cheap_rows.append((role_for[id(t)], won, size, price, tf))

print(f"markets scanned: {n_markets}")
print(f"cheap early BUY trades (price<0.40, time<50%): {len(cheap_rows)}")

def summarize(rows, label):
    if not rows:
        print(f"  {label}: n=0")
        return
    n = len(rows)
    tot_size = sum(r[2] for r in rows)
    won_size = sum(r[2] for r in rows if r[1])
    cost = sum(r[2] * r[3] for r in rows)  # USDC spent
    payout = sum(r[2] for r in rows if r[1])  # winning shares pay $1 each
    pnl = payout - cost
    wr = won_size / tot_size if tot_size else 0
    avg_p = cost / tot_size if tot_size else 0
    ev_per_dollar = (pnl / cost) if cost else 0
    print(f"  {label:8s}: n={n:6d}  size={tot_size:12,.0f}  cost=${cost:10,.0f}  pnl=${pnl:+10,.0f}  win={wr*100:5.1f}%  avg_p={avg_p:.3f}  EV/$={ev_per_dollar*100:+6.1f}%")

print("\n=== By role (cheap early BUYs) ===")
for role in ("taker", "maker", "unknown"):
    summarize([r for r in cheap_rows if r[0] == role], role)
print("--")
summarize(cheap_rows, "ALL")

# Sub-split: by price bucket within taker rows
print("\n=== Taker-only, by price bucket ===")
buckets = [(0.0, 0.10), (0.10, 0.25), (0.25, 0.40)]
for lo, hi in buckets:
    rows = [r for r in cheap_rows if r[0] == "taker" and lo <= r[3] < hi]
    summarize(rows, f"{lo:.2f}-{hi:.2f}")

print("\n=== Maker-only, by price bucket ===")
for lo, hi in buckets:
    rows = [r for r in cheap_rows if r[0] == "maker" and lo <= r[3] < hi]
    summarize(rows, f"{lo:.2f}-{hi:.2f}")
