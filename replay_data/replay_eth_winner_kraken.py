import requests
import pandas as pd
from datetime import datetime, timezone

# ======================================================
# CONFIG — ETH WINNER (KNOWN)
# ======================================================

PAIR = "ETHUSD"
INTERVAL_MIN = 1  # 1-minute candles

# Trade fired: 2026-01-27 19:40 ET
# ET = UTC-5 → 2026-01-28 00:40 UTC
WINDOW_START_UTC = datetime(2026, 1, 28, 0, 0, tzinfo=timezone.utc)
WINDOW_END_UTC   = datetime(2026, 1, 28, 4, 0, tzinfo=timezone.utc)

# ======================================================
# FETCH DATA FROM KRAKEN
# ======================================================

url = "https://api.kraken.com/0/public/OHLC"
params = {
    "pair": PAIR,
    "interval": INTERVAL_MIN,
    "since": int(WINDOW_START_UTC.timestamp())
}

resp = requests.get(url, params=params, timeout=30)
resp.raise_for_status()

payload = resp.json()
if payload.get("error"):
    raise RuntimeError(payload["error"])

data = next(iter(payload["result"].values()))

df = pd.DataFrame(
    data,
    columns=[
        "time","open","high","low","close","vwap","volume","count"
    ]
)

# ======================================================
# CLEAN & FILTER
# ======================================================

df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
df["close"] = df["close"].astype(float)

df = df[
    (df["time"] >= WINDOW_START_UTC) &
    (df["time"] <= WINDOW_END_UTC)
].copy()

if df.empty:
    raise RuntimeError("Window filter returned zero rows")

print(
    f"Loaded window: {df['time'].min()} → {df['time'].max()} "
    f"({len(df)} rows)"
)

# ======================================================
# METRICS (MATCH BOT LOGIC)
# ======================================================

anchor = df.iloc[0]["close"]

df["percent_move"] = (df["close"] - anchor) / anchor * 100
df["slope"] = df["percent_move"].diff()

df["direction"] = df["percent_move"].apply(
    lambda x: 1 if x > 0 else (-1 if x < 0 else 0)
)

df["persistence"] = (
    df["direction"]
    .groupby((df["direction"] != df["direction"].shift()).cumsum())
    .cumcount()
    + 1
)

# ======================================================
# SAVE
# ======================================================

out_path = "eth_winner_replay_kraken.csv"
df.to_csv(out_path, index=False)

print(f"Saved {out_path}")
print(f"Anchor price: {anchor:.4f}")
