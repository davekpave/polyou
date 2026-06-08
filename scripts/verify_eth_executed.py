"""Compute ETH executed-trade EV from archive + any recent execution_log,
joined with outcomes from block_outcomes (which has settled market outcomes)
or from a separate outcomes source.

Goal: lock in / refute the 'ETH -$0.027/trade' figure with raw data.
"""
import csv, os, collections

# 1. Pull executed trades from archive
arch = "logs/execution_log.archive.csv"
executed = []
with open(arch) as f:
    reader = csv.reader(f)
    next(reader, None)
    for row in reader:
        if len(row) < 7: continue
        sym = row[1]
        if sym not in {"BTCUSD","ETHUSD","SOLUSD","XRPUSD"}: continue
        try:
            executed.append({
                "ts": row[0], "sym": sym, "side": row[2],
                "slug": row[3], "snap": float(row[4]) if row[4] else None,
                "rr": float(row[5]),
            })
        except Exception:
            pass

print(f"Archive executed rows: {len(executed)}")
by_sym = collections.Counter(e['sym'] for e in executed)
print(f"By symbol: {dict(by_sym)}")

# 2. Build a slug -> outcome map from block_outcomes (which carries
#    outcome_winner per market). Note: block_outcomes is per BLOCKED candidate
#    but the outcome_winner is per-market, so any row referencing the same
#    market gives the outcome.
slug_outcome = {}  # slug -> "yes"/"no" (winner side)
slug_payoff_yes = {}  # how much YES paid out per share (1 or 0)
for r in csv.DictReader(open("logs/derived/block_outcomes.csv")):
    slug = r.get("contract_slug") or r.get("slug")
    if not slug: continue
    win = r.get("outcome_winner")
    if win:
        slug_outcome[slug] = win

print(f"\nUnique slugs with outcomes in block_outcomes: {len(slug_outcome)}")

# 3. For each executed trade, look up outcome and compute pnl/share
# Side determines which outcome wins: side=YES wins if outcome=yes
pnl_per_share = collections.defaultdict(list)
matched = collections.Counter()
unmatched = collections.Counter()
for e in executed:
    out = slug_outcome.get(e["slug"])
    if not out:
        unmatched[e["sym"]] += 1
        continue
    matched[e["sym"]] += 1
    snap = e["snap"]
    if snap is None: continue
    side = (e["side"] or "").lower()
    # Win if side matches outcome
    won = (side == out.lower())
    # PnL/share = (1 - snap) if won else (-snap)
    pnl = (1.0 - snap) if won else (-snap)
    pnl_per_share[e["sym"]].append((won, pnl, snap, e["rr"]))

print(f"\nMatched (have outcome): {dict(matched)}")
print(f"Unmatched (no outcome in block_outcomes): {dict(unmatched)}")

print("\nPer-symbol executed-trade performance (matched only):")
print(f"{'sym':>8}{'n':>6}{'wr':>9}{'mean_pnl/sh':>14}{'sum_pnl/sh':>14}")
for sym in ["BTCUSD","ETHUSD","SOLUSD","XRPUSD"]:
    arr = pnl_per_share[sym]
    if not arr: 
        print(f"{sym:>8}     -  (no matches)")
        continue
    n = len(arr)
    wr = sum(1 for a in arr if a[0]) / n
    mean = sum(a[1] for a in arr) / n
    tot = sum(a[1] for a in arr)
    print(f"{sym:>8}{n:>6}{wr:>9.1%}{mean:>+14.4f}{tot:>+14.2f}")
