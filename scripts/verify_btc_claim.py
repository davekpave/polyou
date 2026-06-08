"""Re-check the BTC claim more carefully.

Crucial nuance I missed: rr_blocks.csv contains candidates the bot REJECTED.
So filtering them by rr >= threshold tells us about trades we'd UNLOCK by
lowering thresholds, NOT about how BTC has been performing in the trades the
bot ACTUALLY took.

This script:
  1. Counts blocked-BTC EV at each threshold (the original claim).
  2. Compares to ETH and SOL blocked EV at each threshold (apples to apples).
  3. Loads execution_log + archive to see actual BTC trade performance.
  4. Computes BTC blocked-EV at thresholds *above* the old STRICT req (0.44),
     since these would NOT have been blocked by the old tier system either
     (they would only be blocked by VIP/STANDARD-classified candidates being
     subjected to a uniform 0.44+ filter).
"""
import csv, collections, os

rows = list(csv.DictReader(open("logs/derived/block_outcomes.csv")))
parsed = []
for r in rows:
    try:
        parsed.append((
            float(r["signal_rr"]),
            int(r["block_won"]),
            float(r["payoff_per_dollar"]),
            r["tier"],
            r["symbol"],
        ))
    except Exception:
        pass

print(f"Parsed blocks (with outcomes): {len(parsed)}\n")

# 1. By symbol, by threshold
print("=== Blocked-candidate EV by symbol (these are trades the bot REJECTED) ===")
for sym in ["BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD"]:
    s = [p for p in parsed if p[4] == sym]
    if not s:
        continue
    print(f"\n  {sym}  (n_blocked_with_outcome={len(s)})")
    print(f"  {'thresh':>8}{'n_pass':>10}{'win_rate':>12}{'EV/$1':>12}{'total':>10}")
    for thr in [0.15, 0.20, 0.25, 0.275, 0.30, 0.35, 0.40, 0.44, 0.50]:
        sub = [p for p in s if p[0] >= thr]
        n = len(sub)
        if n < 5:
            continue
        wr = sum(p[1] for p in sub) / n
        mean = sum(p[2] for p in sub) / n
        tot = sum(p[2] for p in sub)
        print(f"  {thr:>8.3f}{n:>10}{wr:>12.1%}{mean:>12.4f}{tot:>10.2f}")

# 2. By symbol AND tier, focusing on whether the issue is tier-correlated
print("\n=== Blocked BTC by tier (signal-strength category at the time) ===")
btc = [p for p in parsed if p[4] == "BTCUSD"]
for tier in ["VIP", "STANDARD", "STRICT"]:
    t = [p for p in btc if p[3] == tier]
    if not t:
        continue
    n = len(t)
    wr = sum(p[1] for p in t) / n
    mean = sum(p[2] for p in t) / n
    tot = sum(p[2] for p in t)
    rrs = sorted(p[0] for p in t)
    print(f"  tier={tier:<10} n={n:>4}  rr range=[{rrs[0]:.3f}-{rrs[-1]:.3f}]  "
          f"wr={wr:.1%}  EV/$1={mean:+.4f}  total={tot:+.2f}")

print("\n=== Blocked SOL by tier (for contrast) ===")
sol = [p for p in parsed if p[4] == "SOLUSD"]
for tier in ["VIP", "STANDARD", "STRICT"]:
    t = [p for p in sol if p[3] == tier]
    if not t:
        continue
    n = len(t)
    wr = sum(p[1] for p in t) / n
    mean = sum(p[2] for p in t) / n
    tot = sum(p[2] for p in t)
    rrs = sorted(p[0] for p in t)
    print(f"  tier={tier:<10} n={n:>4}  rr range=[{rrs[0]:.3f}-{rrs[-1]:.3f}]  "
          f"wr={wr:.1%}  EV/$1={mean:+.4f}  total={tot:+.2f}")

# 3. Actual executed BTC trades (from execution log)
print("\n=== Actual executed trades from logs/execution_log.archive.csv (if parseable) ===")
arch = "logs/execution_log.archive.csv"
if os.path.exists(arch):
    # Try reading; the file has variable columns. Just count by symbol and rr_pass
    with open(arch) as f:
        reader = csv.reader(f)
        header = next(reader)
        # Header: timestamp,symbol,side,contract_slug,snapshot_price,signal_rr,rr_pass,...
        # but actually the first row had only short header. Let's just look for
        # 'BTCUSD' / 'ETHUSD' / 'SOLUSD' in rows.
        sym_idx = 1
        snap_idx = 4
        rr_idx = 5
        rr_pass_idx = 6
        counts = collections.Counter()
        rr_by_sym = collections.defaultdict(list)
        for row in reader:
            if len(row) < 7:
                continue
            sym = row[sym_idx]
            try:
                rr = float(row[rr_idx])
                rr_by_sym[sym].append(rr)
                counts[(sym, row[rr_pass_idx])] += 1
            except Exception:
                pass
        print("  rr_pass counts by (symbol, rr_pass):")
        for k, v in sorted(counts.items()):
            print(f"    {k}: {v}")
        print("\n  signal_rr distribution per symbol of executed candidates:")
        for sym, vals in rr_by_sym.items():
            vals.sort()
            n = len(vals)
            if n == 0: continue
            print(f"    {sym}: n={n}  min={vals[0]:.3f}  median={vals[n//2]:.3f}  "
                  f"max={vals[-1]:.3f}")

# 4. Honest framing: what fraction of BLOCKED BTC at each threshold would
#    actually have been ADMITTED under the OLD tier system?
# Old tier req:  VIP=0.275  STANDARD=0.366  STRICT=0.44
# A blocked row was blocked because rr < req_for_its_tier.
# So at flat threshold T, the rows that "newly pass" are those where
#   rr >= T  AND  rr < tier_req
# That's the population that was blocked before but would now be admitted.
print("\n=== BTC: NEW trades that would be admitted at flat threshold T ===")
print("    (i.e. rr >= T  AND  the row was blocked under old tier rule)")
TIER_REQ = {"VIP": 0.275, "STANDARD": 0.366, "STRICT": 0.44}
for thr in [0.20, 0.25, 0.275, 0.30, 0.35, 0.40]:
    new_admits = [p for p in btc if p[0] >= thr and p[0] < TIER_REQ.get(p[3], 1.0)]
    n = len(new_admits)
    if n == 0:
        print(f"  thr={thr:.3f}: no new admissions")
        continue
    wr = sum(p[1] for p in new_admits) / n
    mean = sum(p[2] for p in new_admits) / n
    tot = sum(p[2] for p in new_admits)
    print(f"  thr={thr:.3f}: n_new={n:>4}  wr={wr:.1%}  EV/$1={mean:+.4f}  total={tot:+.2f}")
