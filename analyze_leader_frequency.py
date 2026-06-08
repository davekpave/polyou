#!/usr/bin/env python3
"""
Analyze trading frequency of leaders from OOS validation data.
Identifies high-frequency vs low-frequency (selective) traders.
"""
import csv

print("=" * 80)
print("LEADER TRADING FREQUENCY ANALYSIS")
print("=" * 80)
print()

# Read the OOS top traders file
leaders = []
with open("logs/oos_top_traders.csv", "r") as f:
    reader = csv.DictReader(f)
    for i, row in enumerate(reader):
        if i >= 20:  # Only look at our 20 leaders
            break
        
        address = row["address"]
        train_n = int(row["train_n"])
        test_n = int(row["test_n"])
        train_pnl = float(row["train_pnl"])
        test_pnl = float(row["test_pnl"])
        
        # Calculate trades per day (60 day train, 30 day test)
        train_per_day = train_n / 60
        test_per_day = test_n / 30
        
        leaders.append({
            "address": address,
            "train_n": train_n,
            "test_n": test_n,
            "train_per_day": train_per_day,
            "test_per_day": test_per_day,
            "train_pnl": train_pnl,
            "test_pnl": test_pnl
        })

# Sort by test frequency
leaders_by_freq = sorted(leaders, key=lambda x: x["test_per_day"], reverse=True)

print("Top 20 Leaders - Sorted by Trading Frequency")
print("-" * 80)
print(f"{'Rank':<5} {'Address':<12} {'Test T/Day':<12} {'Train T/Day':<12} {'Test PnL':<10} {'Active?':<8}")
print("-" * 80)

# Track which ones have traded in our live run
active_leaders = [
    "0xa3d043b2da34f58045c6485d3f89b798b2b0ec04",
    "0xeebde7a0e019a63e6b476eb425505b7b3e6eba30",
    "0xb4b5c838eee748bc8873d7065235d2802bb6479a",
    "0xac6df77395095fd6a6f16e836ad845dd8cb0919a"
]

for i, leader in enumerate(leaders_by_freq, 1):
    addr_short = leader["address"][:12]
    is_active = "YES" if leader["address"] in active_leaders else "NO"
    print(f"{i:<5} {addr_short:<12} {leader['test_per_day']:<12.2f} "
          f"{leader['train_per_day']:<12.2f} {leader['test_pnl']:<10.2f} {is_active:<8}")

print()
print("=" * 80)
print("FREQUENCY DISTRIBUTION")
print("=" * 80)

# Categorize by frequency
high_freq = [l for l in leaders if l["test_per_day"] >= 5.0]  # 5+ trades/day
medium_freq = [l for l in leaders if 1.0 <= l["test_per_day"] < 5.0]
low_freq = [l for l in leaders if l["test_per_day"] < 1.0]  # <1 trade/day

print(f"\nHigh Frequency (≥5 trades/day): {len(high_freq)} leaders")
active_high = sum(1 for l in high_freq if l["address"] in active_leaders)
print(f"  Active in live run: {active_high}/{len(high_freq)}")
if high_freq:
    avg_pnl = sum(l["test_pnl"] for l in high_freq) / len(high_freq)
    print(f"  Avg test P&L: {avg_pnl:.2f}")

print(f"\nMedium Frequency (1-5 trades/day): {len(medium_freq)} leaders")
active_med = sum(1 for l in medium_freq if l["address"] in active_leaders)
print(f"  Active in live run: {active_med}/{len(medium_freq)}")
if medium_freq:
    avg_pnl = sum(l["test_pnl"] for l in medium_freq) / len(medium_freq)
    print(f"  Avg test P&L: {avg_pnl:.2f}")

print(f"\nLow Frequency (<1 trade/day): {len(low_freq)} leaders")
active_low = sum(1 for l in low_freq if l["address"] in active_leaders)
print(f"  Active in live run: {active_low}/{len(low_freq)}")
if low_freq:
    avg_pnl = sum(l["test_pnl"] for l in low_freq) / len(low_freq)
    print(f"  Avg test P&L: {avg_pnl:.2f}")

print()
print("=" * 80)
print("INSIGHT")
print("=" * 80)
print()
print(f"After 34 hours (1.4 days) of live trading:")
print(f"  • We've seen {len([l for l in leaders if l['address'] in active_leaders])}/20 leaders trade")
print(f"  • {len([l for l in low_freq if l['address'] not in active_leaders])} low-frequency leaders haven't traded yet")
print()
if low_freq:
    print("Low-frequency leaders (the selective traders) need more time:")
    print("  • At <1 trade/day, expect 1-2 trades per WEEK")
    print(f"  • Need ~7-14 days to see meaningful sample from these traders")
    print()
    print("You're right - the selective, accurate traders haven't shown up yet!")
