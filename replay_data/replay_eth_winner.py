import requests
import pandas as pd
from datetime import datetime, timezone

# ========================
# CONFIG
# ========================
PAIR = "XETHZUSD"   # Kraken ETH/USD
INTERVAL = 1        # 1-minute candles

# ETH winner window
# 2026-01-27 19:00–23:00 ET
# = 2026-01-28 00:00–04:00 UTC
WINDOW_START = datetime(2026, 1, 28, 0, 0, tzinfo=timezone.utc)
WINDOW_END   = datetime(2026, 1, 28, 4, 0, tzinfo=timezone.utc)

# Pull a bit earlier to be safe
SINCE = int((WINDOW_START.timestamp() - 3600))

# ========================
# FETCH DATA
# ========================
url = "https://api.kraken.com/0/public/OHLC"
params = {
    "pair": PAIR,
    "interval": INTERVAL,
    "since": SINCE,
}

resp = requests.get(url, params=params, timeout=20)
resp.raise_for_status()
payload = resp.json()

if payload.get("error"):
    raise RuntimeError(f"Kraken API error: {payload['error']}")

pair_key = [k for k in payload["result"].keys() if k != "last"][0]
raw = payload["result"][pair_key]

df = pd.DataFrame(
    raw,
    columns=[
        "time",
        "open",
        "high",
        "low",
        "close",
        "vwap",
        "volume",
        "count",
    ],
)

df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
df["close"] = df["close"].astype(float)

print("Fetched range:",
      df["time"].min(),
      "→",
      df["time"].max())

# ========================
# WINDOW FILTER
# ========================
df = df[(df["time"] >= WINDOW_START) & (df["time"] <= WINDOW_END)].copy()

if df.empty:
    raise RuntimeError("Data loaded but window filter returned zero rows")

# ========================
# METRICS (IDENTICAL TO BOT)
# ========================
anchor = df.iloc[0]["close"]

df["percent_move"] = (df["close"] - anchor) / anchor * 100
df["slope"] = df["percent_move"].diff()

df["direction"] = df["percent_move"].apply(
    lambda x: 1 if x > 0 else -1
)

df["persistence"] = (
    df["direction"]
    .groupby((df["direction"] != df["direction"].shift()).cumsum())
    .cumcount()
    + 1
)

# ========================
# SAVE
# ========================
out = "eth_winner_kraken_replay.csv"
df.to_csv(out, index=False)

print("Saved:", out)
print("Rows:", len(df))
print("Anchor price:", anchor)
print("Window:", df["time"].min(), "→", df["time"].max())
