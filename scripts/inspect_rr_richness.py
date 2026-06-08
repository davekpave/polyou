import pandas as pd

df = pd.read_csv("logs/rr_blocks.csv", engine="python", on_bad_lines="skip")
df["ts"] = pd.to_datetime(df["ts_iso"], utc=True, errors="coerce")
rich = df[df["regime"].notna() & (df["regime"].astype(str) != "")]
print(f"total rows: {len(df):,}")
print(f"rich rows : {len(rich):,}")
if len(rich):
    print(f"rich first: {rich['ts'].min()}")
    print(f"rich last : {rich['ts'].max()}")
    span_h = (rich["ts"].max() - rich["ts"].min()).total_seconds() / 3600
    print(f"rich span : {span_h:.2f}h")
    print()
    print("regime counts:")
    print(rich["regime"].value_counts().to_string())
    print()
    print("dominant_recent_gate counts:")
    print(rich["dominant_recent_gate"].value_counts().head(10).to_string())
