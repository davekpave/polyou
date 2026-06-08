"""For each candidate flat req_rr threshold, compute pass count, win rate,
and expected payoff per $1 staked using actual market outcomes from
logs/derived/block_outcomes.csv.

block_won: 1 if the side won, 0 if it lost.
payoff_per_dollar: payoff per $1 staked at the snapshot price (= 1/p - 1
                   for a winner, -1 for a loser).
EV per $1 = mean(payoff_per_dollar) across passing rows
          = win_rate * mean(payoff|win) - (1 - win_rate)
"""
import csv
import collections

rows = list(csv.DictReader(open("logs/derived/block_outcomes.csv")))
print(f"Total scored rows: {len(rows)}")

# parse
parsed = []
for r in rows:
    try:
        rr = float(r["signal_rr"])
        won = int(r["block_won"])
        payoff = float(r["payoff_per_dollar"])
        tier = r["tier"]
        sym = r["symbol"]
        side = r["side"]
        parsed.append((rr, won, payoff, tier, sym, side))
    except Exception:
        pass

print(f"Parsed: {len(parsed)}\n")

print("=== EV by flat req_rr threshold (all symbols, all tiers) ===")
print(f"{'thresh':>8}{'n_pass':>10}{'win_rate':>12}{'mean_payoff':>14}{'total_$_per_$1':>18}")
for thresh in [0.10, 0.15, 0.20, 0.25, 0.275, 0.30, 0.35, 0.366, 0.40, 0.44]:
    passes = [(w, p) for rr, w, p, *_ in parsed if rr >= thresh]
    n = len(passes)
    if n == 0:
        continue
    wr = sum(w for w, _ in passes) / n
    mean_pay = sum(p for _, p in passes) / n
    total = sum(p for _, p in passes)
    print(f"{thresh:>8.3f}{n:>10}{wr:>12.1%}{mean_pay:>14.4f}{total:>18.2f}")

print("\n=== Same, broken down by tier (the tier the bot would have assigned) ===")
for tier in ["VIP", "STANDARD", "STRICT"]:
    tparsed = [p for p in parsed if p[3] == tier]
    print(f"\n--- tier={tier}  (n={len(tparsed)}) ---")
    print(f"{'thresh':>8}{'n_pass':>10}{'win_rate':>12}{'mean_payoff':>14}{'total_$_per_$1':>18}")
    for thresh in [0.10, 0.15, 0.20, 0.25, 0.275, 0.30, 0.35, 0.366, 0.40, 0.44]:
        passes = [(w, p) for rr, w, p, *_ in tparsed if rr >= thresh]
        n = len(passes)
        if n == 0:
            continue
        wr = sum(w for w, _ in passes) / n
        mean_pay = sum(p for _, p in passes) / n
        total = sum(p for _, p in passes)
        print(f"{thresh:>8.3f}{n:>10}{wr:>12.1%}{mean_pay:>14.4f}{total:>18.2f}")

print("\n=== Same, broken down by symbol ===")
for sym in sorted(set(p[4] for p in parsed)):
    sparsed = [p for p in parsed if p[4] == sym]
    print(f"\n--- {sym}  (n={len(sparsed)}) ---")
    print(f"{'thresh':>8}{'n_pass':>10}{'win_rate':>12}{'mean_payoff':>14}{'total_$_per_$1':>18}")
    for thresh in [0.15, 0.20, 0.25, 0.275, 0.30, 0.35, 0.40]:
        passes = [(w, p) for rr, w, p, *_ in sparsed if rr >= thresh]
        n = len(passes)
        if n == 0:
            continue
        wr = sum(w for w, _ in passes) / n
        mean_pay = sum(p for _, p in passes) / n
        total = sum(p for _, p in passes)
        print(f"{thresh:>8.3f}{n:>10}{wr:>12.1%}{mean_pay:>14.4f}{total:>18.2f}")
