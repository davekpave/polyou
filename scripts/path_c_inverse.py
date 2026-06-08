"""Path C analysis: what if we had SOLD each token at entry_price instead of bought?

For a binary at price P:
  BUY  and hold to settlement: pnl = +1 - P (if predicted side wins) or -P (if loses).
  SELL and hold to settlement: pnl = -1 + P (if predicted side wins) or +P (if loses).

The bot's actual data has some trades exit early at EXPIRY_BID (~0.989) instead of settling.
For the SELL inverse, we model two scenarios:
  (a) Naive: sell-and-hold-to-settlement (no early cover).
  (b) Match-bot: invert each actual exit price (cover at ~1 - 0.989 = 0.011 if the buy
      side would have early-exited; cover at $1 if predicted side wins to settlement,
      cover at $0 if loses to settlement).
"""
import csv

rows = list(csv.DictReader(open("logs/shadow_exits.csv")))


def f(x):
    try:
        return float(x)
    except Exception:
        return None


print(f"Total shadow trades: {len(rows)}\n")

# ---------- BUY side (actual bot) ----------
buy_total = sum(f(r["profit_per_share"]) for r in rows)
buy_wins = sum(1 for r in rows if f(r["profit_per_share"]) > 0)
print(f"BUY (actual bot):")
print(f"  total pnl/share = ${buy_total:+.2f}  WR = {buy_wins}/{len(rows)} = {buy_wins/len(rows):.1%}")
print(f"  mean per trade  = ${buy_total/len(rows):+.4f}")

# ---------- SELL inverse, naive sell-and-settle ----------
print(f"\nSELL inverse (naive: sell at entry, hold to settlement):")
naive_total = 0.0
naive_wins = 0
for r in rows:
    entry = f(r["entry_price"])
    pps = f(r["profit_per_share"])
    # 'win' means the bot's predicted side won. For the SELL inverse we want it to LOSE.
    bot_won = pps > 0  # bot won if it made any positive pnl
    # But pps>0 includes early-exit wins. For "predicted side won" we need:
    # exit_type SETTLED_ZERO means predicted side LOST. EXPIRY_BID means predicted side WON
    # (almost always settles to $1 a few seconds later).
    pred_won = (r["exit_type"] == "EXPIRY_BID")
    if pred_won:
        # we sold at entry, must pay $1 at settle
        sell_pnl = entry - 1.0
    else:
        # predicted side lost (settled to 0); we keep the entry premium
        sell_pnl = entry
        naive_wins += 1
    naive_total += sell_pnl
print(f"  total pnl/share = ${naive_total:+.2f}  WR = {naive_wins}/{len(rows)} = {naive_wins/len(rows):.1%}")
print(f"  mean per trade  = ${naive_total/len(rows):+.4f}")

# Per-side breakdown
print(f"\nSELL inverse, per-side:")
for side in ("UP", "DOWN"):
    sub = [r for r in rows if r["side"] == side]
    side_pnl = 0.0
    side_wins = 0
    for r in sub:
        entry = f(r["entry_price"])
        if r["exit_type"] == "EXPIRY_BID":
            side_pnl += entry - 1.0
        else:
            side_pnl += entry
            side_wins += 1
    print(
        f"  {side}: n={len(sub):2d}  WR={side_wins}/{len(sub)}={side_wins/len(sub):.1%}  "
        f"total=${side_pnl:+.2f}  mean=${side_pnl/len(sub):+.4f}"
    )

# ---------- Reality check: spread cost on selling ----------
# When we BUY at entry, snapshot_price = clob_ask + 0.02 (we cross spread).
# When we SELL at entry, we'd hit clob_bid, which is typically 0.01-0.02 BELOW clob_ask.
# So the actual sell price would be entry_price - ~0.03 (snapshot was ask + 0.02, bid is ~ask - 0.01).
print(f"\nSELL inverse with ~3¢ spread cost (sell at entry - 0.03 instead of entry):")
realistic_total = 0.0
realistic_wins = 0
for r in rows:
    entry = f(r["entry_price"])
    sell_price = entry - 0.03  # crossing spread to hit bid
    if r["exit_type"] == "EXPIRY_BID":
        sell_pnl = sell_price - 1.0
    else:
        sell_pnl = sell_price
        realistic_wins += 1
    realistic_total += sell_pnl
print(f"  total pnl/share = ${realistic_total:+.2f}  WR = {realistic_wins}/{len(rows)}")
print(f"  mean per trade  = ${realistic_total/len(rows):+.4f}")

print(f"\nPer-side (with 3¢ spread):")
for side in ("UP", "DOWN"):
    sub = [r for r in rows if r["side"] == side]
    side_pnl = 0.0
    for r in sub:
        entry = f(r["entry_price"]) - 0.03
        if r["exit_type"] == "EXPIRY_BID":
            side_pnl += entry - 1.0
        else:
            side_pnl += entry
    print(f"  {side}: n={len(sub):2d}  total=${side_pnl:+.2f}  mean=${side_pnl/len(sub):+.4f}")
