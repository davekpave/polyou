import zipfile
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone, timedelta

# ======================================================
# CONFIG — ETH WINNER (KNOWN)
# ======================================================

SYMBOL = "ETHUSDT"
INTERVAL = "1m"

# ETH winner:
# Trade fired: 2026-01-27 19:40 ET
# ET = UTC-5 → 2026-01-28 00:40 UTC
#
# Replay the full 4H market window in UTC
WINDOW_START_UTC = datetime(2026, 1, 28, 0, 0, tzinfo=timezone.utc)
WINDOW_END_UTC   = datetime(2026, 1, 28, 4, 0, tzinfo=timezone.utc)

DATA_DIR = Path("binance_data")
DATA_DIR.mkdir(exist_ok=True)

# ======================================================
# HELPERS
# ======================================================

def download_daily_zip(day_utc: datetime):
    date_str = day_utc.strftime("%Y-%m-%d")
    url = (
        f"https://data.binance.vision/data/spot/daily/klines/"
        f"{SYMBOL}/{INTERVAL}/{SYMBOL}-{INTERVAL}-{date_str}.zip"
    )
    zip_path = DATA_DIR / f"{SYMBOL}-{INTERVAL}-{date_str}.zip"

    if zip_path.exists():
        return zip_path

    print(f"Downloading: {url}")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    with open(zip_path, "wb") as f:
        f.write(resp.content)

    return zip_path


def load_zip_to_df(zip_path: Path):
    with zipfile.ZipFile(zip_path, "r") as z:
        csv_name = z.namelist()[0]
        with z.open(csv_name) as f:
            df = pd.read_csv(
                f,
                header=None,
                names=[
                    "open_time","open","high","low","close","volume",
                    "close_time","qav","num_trades","taker_base",
                    "taker_quote","ignore"
                ],
            )
    return df


# ======================================================
# DOWNLOAD REQUIRED DAYS
# ======================================================

days = {
    WINDOW_START_UTC.date(),
    (WINDOW_START_UTC - timedelta(days=1)).date(),
}

dfs = []

for day in days:
    zip_path = download_daily_zip(
        datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    )
    dfs.append(load_zip_to_df(zip_path))

df = pd.concat(dfs, ignore_index=True)

# ======================================================
# CLEAN & FILTER
# ======================================================

df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
df["close"] = df["close"].astype(float)

mask = (df["open_time"] >= WINDOW_START_UTC) & (df["open_time"] <= WINDOW_END_UTC)
df = df.loc[mask].copy()

if df.empty:
    raise RuntimeError("Window filter returned zero rows — check timestamps")

print(
    f"Loaded window: {df['open_time'].min()} → {df['open_time'].max()} "
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

out_path = Path("eth_winner_replay.csv")
df.to_csv(out_path, index=False)

print(f"Saved {out_path}")
print(f"Anchor price: {anchor:.4f}")
