"""Compare winners vs losers across feature buckets in shadow_exits.csv."""
import csv
from collections import defaultdict
from statistics import mean, median


with open("logs/shadow_exits.csv", "r", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))


def f(r, k):
    try:
        return float(r[k])
    except (ValueError, KeyError, TypeError):
        return None


def is_win(r):
    return float(r["profit_per_share"]) > 0


wins = [r for r in rows if is_win(r)]
losses = [r for r in rows if not is_win(r)]

print(f"n={len(rows)}  W={len(wins)}  L={len(losses)}\n")


def bucket_stats(field, label=None, value_fn=None):
    label = label or field
    if value_fn is None:
        def value_fn(r):
            return f(r, field)
    w_vals = [v for r in wins if (v := value_fn(r)) is not None]
    l_vals = [v for r in losses if (v := value_fn(r)) is not None]
    if not w_vals or not l_vals:
        print(f"  {label:30s} insufficient data")
        return
    print(
        f"  {label:30s} W: mean={mean(w_vals):8.4f} med={median(w_vals):8.4f}  "
        f"L: mean={mean(l_vals):8.4f} med={median(l_vals):8.4f}"
    )


print("== continuous features (winners vs losers) ==")
bucket_stats("entry_price")
bucket_stats("snapshot_price")
bucket_stats("signal_rr")
bucket_stats("signal_quality")
bucket_stats("hold_seconds")
bucket_stats("spread_bps_at_exit")


def cross(field, value_fn=None):
    if value_fn is None:
        def value_fn(r):
            return r.get(field)
    g = defaultdict(lambda: [0, 0, 0.0])
    for r in rows:
        k = value_fn(r)
        g[k][0] += 1
        if is_win(r):
            g[k][1] += 1
        g[k][2] += float(r["profit_per_share"])
    print(f"\n== by {field} ==")
    for k in sorted(g, key=lambda x: (str(x))):
        n, w, net = g[k]
        wr = w / n if n else 0
        print(f"  {str(k):20s} n={n:3d}  W={w:2d}  WR={wr:.0%}  net=${net:+7.2f}")


cross("symbol")
cross("side")
cross("exit_type")


# Bucket entry_price for win-rate curve
print("\n== WR by entry_price bucket ==")
buckets = [(0.50, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.01)]
for lo, hi in buckets:
    sub = [r for r in rows if lo <= float(r["entry_price"]) < hi]
    if not sub:
        print(f"  [{lo:.2f},{hi:.2f})  n=0")
        continue
    w = sum(1 for r in sub if is_win(r))
    net = sum(float(r["profit_per_share"]) for r in sub)
    print(
        f"  [{lo:.2f},{hi:.2f})  n={len(sub):3d}  W={w:2d}  "
        f"WR={w/len(sub):.0%}  net=${net:+7.2f}  mean=${net/len(sub):+.3f}"
    )

print("\n== WR by signal_rr bucket ==")
rr_buckets = [(-1.0, 0.0), (0.0, 0.10), (0.10, 0.25), (0.25, 0.50), (0.50, 999)]
for lo, hi in rr_buckets:
    sub = []
    for r in rows:
        v = f(r, "signal_rr")
        if v is None:
            continue
        if lo <= v < hi:
            sub.append(r)
    if not sub:
        print(f"  [{lo:.2f},{hi:.2f})  n=0")
        continue
    w = sum(1 for r in sub if is_win(r))
    net = sum(float(r["profit_per_share"]) for r in sub)
    print(
        f"  [{lo:.2f},{hi:.2f})  n={len(sub):3d}  W={w:2d}  "
        f"WR={w/len(sub):.0%}  net=${net:+7.2f}  mean=${net/len(sub):+.3f}"
    )

print("\n== UP-side by entry_price bucket ==")
up = [r for r in rows if r["side"] == "UP"]
for lo, hi in buckets:
    sub = [r for r in up if lo <= float(r["entry_price"]) < hi]
    if not sub:
        continue
    w = sum(1 for r in sub if is_win(r))
    net = sum(float(r["profit_per_share"]) for r in sub)
    print(
        f"  UP [{lo:.2f},{hi:.2f})  n={len(sub):3d}  W={w:2d}  "
        f"WR={w/len(sub):.0%}  net=${net:+7.2f}"
    )

print("\n== DOWN-side by entry_price bucket ==")
dn = [r for r in rows if r["side"] == "DOWN"]
for lo, hi in buckets:
    sub = [r for r in dn if lo <= float(r["entry_price"]) < hi]
    if not sub:
        continue
    w = sum(1 for r in sub if is_win(r))
    net = sum(float(r["profit_per_share"]) for r in sub)
    print(
        f"  DOWN [{lo:.2f},{hi:.2f})  n={len(sub):3d}  W={w:2d}  "
        f"WR={w/len(sub):.0%}  net=${net:+7.2f}"
    )
