"""
Lag backtest v3 — use bot's actual on-chain resolution as truth.

For each market:
  - bot bet side_bet (UP/DOWN) and predicted_side_won is 0 or 1.
  - => We KNOW which side won: side_bet won iff predicted_side_won==1.
  - The other side won iff predicted_side_won==0.

Backtest logic same as v2 but truth comes from the bot.
Also: report P&L conditional on whether our trade matched bot's side.
"""
import bisect
import csv
import glob
from collections import defaultdict


def load_chainlink_all():
    by_sym = defaultdict(list)
    for f in sorted(glob.glob("logs/chainlink_prices_*.csv")):
        with open(f, "r") as fh:
            r = csv.DictReader(fh)
            for row in r:
                try:
                    by_sym[row["symbol"]].append((float(row["ts_epoch"]), float(row["price"])))
                except Exception:
                    continue
    out = {}
    for sym, pairs in by_sym.items():
        pairs.sort()
        out[sym] = ([p[0] for p in pairs], [p[1] for p in pairs])
    return out


def cex_at(cex, t):
    ts, px = cex
    i = bisect.bisect_right(ts, t) - 1
    if i < 0:
        return None
    return (ts[i], px[i])


def pm_last_at_or_before(pm_sorted, t):
    ts = [p[0] for p in pm_sorted]
    i = bisect.bisect_right(ts, t) - 1
    if i < 0:
        return None
    return pm_sorted[i]


def main():
    LOOKBACK_S = 60
    HOLD_LATEST_S = 30
    MARKUP = 0.02

    cex_by_sym = load_chainlink_all()
    rows = list(csv.DictReader(open("logs/lag_dataset.csv")))
    groups = defaultdict(list)
    for r in rows:
        groups[(r["slug"], r["token_id"])].append(r)

    bot_trades = list(csv.DictReader(open("logs/shadow_exits.csv")))
    bot_by_token = {t["token_id"]: t for t in bot_trades}

    market_meta = {}
    pm_by_market = {}
    for key, gr in groups.items():
        first = gr[0]
        sym = first["symbol"]
        win_start = int(first["win_start"])
        win_end = int(first["win_end"])
        bot = bot_by_token.get(first["token_id"])
        if bot is None:
            continue
        if bot["predicted_side_won"] not in ("0", "1"):
            continue
        side_bet = bot["side"]
        bet_won = int(bot["predicted_side_won"])
        # truth: which side actually won
        up_won = bet_won if side_bet == "UP" else (1 - bet_won)
        market_meta[key] = {
            "sym": sym,
            "win_start": win_start,
            "win_end": win_end,
            "side_bet": side_bet,
            "up_won": up_won,
            "token_id": first["token_id"],
            "bot_entry_price": float(bot["entry_price"]),
            "bot_exit_type": bot["exit_type"],
            "bot_pnl": float(bot["profit_per_share"]),
        }
        pm_by_market[key] = sorted(
            [(float(r["pm_t"]), float(r["pm_px"])) for r in gr]
        )

    print(f"markets with truth: {len(market_meta)}")

    print()
    print("=== Q2 v3: backtest with on-chain truth ===")
    print(
        f"{'K_bps':>6s}  {'n':>4s}  {'win%':>6s}  {'avg_ask':>8s}  "
        f"{'avg_pnl':>8s}  {'total':>9s}"
    )
    by_K_results = {}
    for K in [3, 5, 8, 10, 15, 20, 30]:
        n = 0
        wins = 0
        sum_ask = 0.0
        sum_pnl = 0.0
        same_side_n = 0
        same_side_wins = 0
        same_side_pnl = 0.0
        diff_side_n = 0
        diff_side_wins = 0
        diff_side_pnl = 0.0
        for key, meta in market_meta.items():
            sym = meta["sym"]
            cex = cex_by_sym[sym]
            pm = pm_by_market[key]
            cex_ts, cex_px = cex
            i_lo = bisect.bisect_left(cex_ts, meta["win_start"] + LOOKBACK_S)
            i_hi = bisect.bisect_right(cex_ts, meta["win_end"] - HOLD_LATEST_S)
            for i in range(i_lo, i_hi):
                t = cex_ts[i]
                back = cex_at(cex, t - LOOKBACK_S)
                if back is None:
                    continue
                d_bps = (cex_px[i] - back[1]) / back[1] * 1e4
                if abs(d_bps) < K:
                    continue
                pm_last = pm_last_at_or_before(pm, t)
                if pm_last is None:
                    continue
                _, pm_px_bet_side = pm_last
                our_side = "UP" if d_bps > 0 else "DOWN"
                if our_side == meta["side_bet"]:
                    px_our = pm_px_bet_side
                else:
                    px_our = 1.0 - pm_px_bet_side
                ask = min(0.99, px_our + MARKUP)
                we_won = 1 if (
                    (our_side == "UP" and meta["up_won"] == 1)
                    or (our_side == "DOWN" and meta["up_won"] == 0)
                ) else 0
                pnl = (1.0 if we_won else 0.0) - ask
                n += 1
                wins += we_won
                sum_ask += ask
                sum_pnl += pnl
                if our_side == meta["side_bet"]:
                    same_side_n += 1
                    same_side_wins += we_won
                    same_side_pnl += pnl
                else:
                    diff_side_n += 1
                    diff_side_wins += we_won
                    diff_side_pnl += pnl
                break
        if n == 0:
            continue
        print(
            f"{K:6d}  {n:4d}  {100*wins/n:6.2f}  {sum_ask/n:8.4f}  "
            f"{sum_pnl/n:8.4f}  {sum_pnl:+9.2f}"
        )
        by_K_results[K] = (n, wins, sum_pnl, same_side_n, same_side_wins, same_side_pnl,
                           diff_side_n, diff_side_wins, diff_side_pnl)

    print()
    print("=== Same-side vs different-side from bot, at K=5 ===")
    K = 5
    n, wins, pnl, ssn, ssw, ssp, dsn, dsw, dsp = by_K_results[K]
    if ssn:
        print(f"  same side as bot : n={ssn:3d}  win%={100*ssw/ssn:6.2f}  pnl={ssp:+.2f}")
    if dsn:
        print(f"  diff side as bot : n={dsn:3d}  win%={100*dsw/dsn:6.2f}  pnl={dsp:+.2f}")

    # also report bot's actual P&L on same overlap markets at K=5
    print()
    print("=== Bot's actual P&L on same markets (regardless of trigger) ===")
    bot_pnl_total = sum(m["bot_pnl"] for m in market_meta.values())
    bot_wins = sum(1 for m in market_meta.values()
                   if (m["side_bet"] == "UP" and m["up_won"] == 1)
                   or (m["side_bet"] == "DOWN" and m["up_won"] == 0))
    print(f"  bot overall on these markets: n={len(market_meta)}  win%={100*bot_wins/len(market_meta):.2f}  pnl={bot_pnl_total:+.2f}")


if __name__ == "__main__":
    main()
