"""Sanity check the honest-replay analysis. Verify:
1. Are rows duplicated per (token_id, window_start_ts)? If so, results are inflated.
2. Is payoff_per_dollar = (1-sp) [per-share] or (1-sp)/sp [per-dollar]?
3. Does 'block_won' match outcome_winner == side?
4. For near_close: is block_won well-defined or noisy?
5. Time-stability: split honest data into halves; does the 'simple strategy' edge persist?
6. Drop-stale_terminal bias: are stale_terminal trades secretly losses?
"""
from __future__ import annotations

import csv
from collections import defaultdict, Counter
from pathlib import Path
from datetime import datetime

INPUT = Path(__file__).resolve().parent.parent / "logs" / "derived" / "block_outcomes.csv"


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load():
    with INPUT.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def true_payoff_per_dollar(sp, won):
    """If you spend $1 buying YES at price sp:
       - win  -> profit = 1/sp - 1 = (1-sp)/sp
       - loss -> profit = -1
    """
    if won == 1.0:
        return (1.0 - sp) / sp
    return -1.0


def section(title):
    print()
    print("=" * 96)
    print(title)
    print("=" * 96)


def main():
    rows = load()
    section("1. Row duplication by (token_id, window_start_ts)")
    by_market = defaultdict(list)
    for r in rows:
        by_market[(r["token_id"], r["window_start_ts"])].append(r)
    counts = Counter(len(v) for v in by_market.values())
    total_markets = len(by_market)
    total_rows = len(rows)
    print(f"  total rows                        : {total_rows}")
    print(f"  unique (token_id, window) markets : {total_markets}")
    print(f"  rows-per-market distribution      :")
    for k in sorted(counts.keys()):
        print(f"    {k:3d} snapshots: {counts[k]:5d} markets")
    print(f"  mean snapshots per market         : {total_rows/total_markets:.2f}")

    # Check: within a market, do all snapshots agree on outcome_winner / block_won?
    inconsistent = 0
    for k, v in by_market.items():
        winners = {r["outcome_winner"] for r in v}
        wons = {r["block_won"] for r in v}
        if len(winners) > 1 or len(wons) > 1:
            inconsistent += 1
    print(f"  markets w/ inconsistent outcome   : {inconsistent}")

    section("2. payoff_per_dollar semantics check")
    # Look at win rows: payoff vs (1-sp) vs (1-sp)/sp
    sample_wins = [r for r in rows if to_float(r["block_won"]) == 1.0][:8]
    print(f"  {'sp':>6s}  {'paid_csv':>8s}  {'(1-sp)':>8s}  {'(1-sp)/sp':>10s}  match")
    for r in sample_wins:
        sp = to_float(r["snapshot_price"])
        p = to_float(r["payoff_per_dollar"])
        per_share = 1.0 - sp
        per_dollar = (1.0 - sp) / sp if sp > 0 else float("nan")
        which = "per_share(1-sp)" if abs(p - per_share) < 1e-4 else (
                "per_dollar((1-sp)/sp)" if abs(p - per_dollar) < 1e-4 else "neither")
        print(f"  {sp:6.3f}  {p:8.4f}  {per_share:8.4f}  {per_dollar:10.4f}  {which}")
    # Loss rows
    sample_losses = [r for r in rows if to_float(r["block_won"]) == 0.0][:5]
    print()
    print(f"  losses sample:")
    print(f"  {'sp':>6s}  {'paid_csv':>8s}")
    for r in sample_losses:
        sp = to_float(r["snapshot_price"])
        p = to_float(r["payoff_per_dollar"])
        print(f"  {sp:6.3f}  {p:8.4f}")

    section("3. Does block_won align with outcome_winner == side?")
    mismatches = 0
    for r in rows:
        won = to_float(r["block_won"])
        if won is None:
            continue
        expected = 1.0 if r["outcome_winner"] == r["side"] else 0.0
        if won != expected:
            mismatches += 1
    print(f"  rows where block_won != (outcome_winner == side): {mismatches} / {len(rows)}")
    # Break down by label_conf
    by_label = defaultdict(lambda: [0, 0])  # [match, total]
    for r in rows:
        won = to_float(r["block_won"])
        if won is None:
            continue
        expected = 1.0 if r["outcome_winner"] == r["side"] else 0.0
        by_label[r["outcome_label_conf"]][1] += 1
        if won == expected:
            by_label[r["outcome_label_conf"]][0] += 1
    print(f"  by label_conf:")
    for lc in sorted(by_label.keys()):
        m, t = by_label[lc]
        print(f"    {lc:42s}  match={m}/{t} ({100*m/t:.1f}%)")

    section("4. near_close win-rate sanity (per-market dedup)")
    # Dedup to one row per market
    dedup = {}
    for r in rows:
        k = (r["token_id"], r["window_start_ts"])
        if k not in dedup:
            dedup[k] = r
    dedup_rows = list(dedup.values())
    print(f"  unique markets total: {len(dedup_rows)}")
    by_lc = defaultdict(list)
    for r in dedup_rows:
        by_lc[r["outcome_label_conf"]].append(r)
    for lc in sorted(by_lc.keys()):
        sub = by_lc[lc]
        wins = sum(1 for r in sub if to_float(r["block_won"]) == 1.0)
        n = len(sub)
        print(f"    {lc:42s}  n={n:5d}  win={100*wins/n:5.1f}%")

    section("5. Recompute simple strategies — DEDUP + CORRECT EV")
    resolved = [r for r in dedup_rows if r["outcome_label_conf"] in ("strict", "near_close")]

    def evaluate(name, sub):
        n = len(sub)
        if n == 0:
            print(f"  {name:48s}  n=0")
            return
        wins = sum(1 for r in sub if to_float(r["block_won"]) == 1.0)
        snaps = [to_float(r["snapshot_price"]) or 0.0 for r in sub]
        # CORRECTED EV: per dollar invested
        ev_per_dollar = sum(true_payoff_per_dollar(s, to_float(r["block_won"]))
                            for r, s in zip(sub, snaps)) / n
        mean_sp = sum(snaps) / n
        wr = wins / n
        # CSV "payoff_per_dollar" is per-share => to convert to per-dollar profit,
        # winning row contributes (1-sp)/sp, losing row -1. Already in true_payoff.
        edge = wr - mean_sp
        print(f"  {name:48s}  n={n:5d}  win={100*wr:5.1f}%  "
              f"sp̄={mean_sp:.3f}  edge={100*edge:+6.2f}pp  "
              f"EV/$={ev_per_dollar:+.4f}")

    sol = [r for r in resolved if r["symbol"] == "SOLUSD"]
    btc_up = [r for r in resolved if r["symbol"] == "BTCUSD" and r["side"] == "UP"]
    btc_up_band = [r for r in btc_up
                   if (sp := to_float(r["snapshot_price"])) is not None
                   and 0.80 <= sp <= 0.95]
    sol_btc = [r for r in resolved
               if (r["symbol"] == "SOLUSD"
                   or (r["symbol"] == "BTCUSD" and r["side"] == "UP"))]
    sol_floor = [r for r in sol
                 if (sp := to_float(r["snapshot_price"])) is not None and sp <= 0.95]
    sol_btc_floor = [r for r in sol_btc
                     if (sp := to_float(r["snapshot_price"])) is not None and sp <= 0.95]

    evaluate("ALL resolved (dedup, no filter)", resolved)
    evaluate("SOL UP+DOWN, no caps", sol)
    evaluate("SOL UP+DOWN, sp<=0.95", sol_floor)
    evaluate("BTC UP, sp in [0.80, 0.95]", btc_up_band)
    evaluate("SOL + BTC UP combined", sol_btc)
    evaluate("SOL + BTC UP, sp<=0.95", sol_btc_floor)

    section("6. Time stability — split SOL+BTC_UP @ sp<=0.95 into halves")
    sub = sorted(sol_btc_floor, key=lambda r: r["window_start_ts"])
    half = len(sub) // 2
    early = sub[:half]
    late = sub[half:]
    if early:
        ts0 = datetime.fromtimestamp(int(early[0]["window_start_ts"]))
        ts1 = datetime.fromtimestamp(int(early[-1]["window_start_ts"]))
        ts2 = datetime.fromtimestamp(int(late[-1]["window_start_ts"]))
        print(f"  early window: {ts0} .. {ts1}")
        print(f"  late  window: {ts1} .. {ts2}")
    evaluate("EARLY half", early)
    evaluate("LATE  half", late)

    # quartiles
    print()
    print("  quartiles of SOL+BTC_UP @ sp<=0.95 by time:")
    q = len(sub) // 4
    for i in range(4):
        chunk = sub[i*q:(i+1)*q] if i < 3 else sub[i*q:]
        if chunk:
            ts0 = datetime.fromtimestamp(int(chunk[0]["window_start_ts"]))
            ts1 = datetime.fromtimestamp(int(chunk[-1]["window_start_ts"]))
            evaluate(f"  Q{i+1} ({ts0:%Y-%m-%d} .. {ts1:%Y-%m-%d})", chunk)

    section("7. stale_terminal bias check")
    # If we COULD label stale_terminal rows, would the strategy still win?
    # We can't truly know. But check: of stale_terminal rows, how does block_won split?
    stale = [r for r in dedup_rows if r["outcome_label_conf"] == "stale_terminal"]
    print(f"  stale_terminal markets: {len(stale)}")
    if stale:
        wins = sum(1 for r in stale if to_float(r["block_won"]) == 1.0)
        losses = sum(1 for r in stale if to_float(r["block_won"]) == 0.0)
        nan = len(stale) - wins - losses
        print(f"    block_won: wins={wins}  losses={losses}  unset/NaN={nan}")
        print(f"    => block_won IS populated for stale_terminal? "
              f"({'yes' if wins+losses>0 else 'no'})")
        # If yes, simulate strategy including stale_terminal
        if wins + losses > len(stale) * 0.5:
            section("7b. Simple strategy including stale_terminal (worst-case sanity)")
            full = [r for r in dedup_rows
                    if r["outcome_label_conf"] not in
                       ("near_close_yes_no_disagree",
                        "near_close_indeterminate",
                        "near_close_indeterminate_yes_no_disagree")]
            sb = [r for r in full
                  if (r["symbol"] == "SOLUSD"
                      or (r["symbol"] == "BTCUSD" and r["side"] == "UP"))
                  and (sp := to_float(r["snapshot_price"])) is not None
                  and sp <= 0.95]
            evaluate("SOL+BTC_UP @ sp<=0.95 INCLUDING stale_terminal", sb)


if __name__ == "__main__":
    main()
