import pandas as pd
files = ['logs/rr_blocks.csv', 'logs/rr_blocks_v1.csv', 'logs/rr_blocks_v2.csv']
dfs = [pd.read_csv(f, on_bad_lines='skip', engine='python') for f in files]
df = pd.concat(dfs, ignore_index=True)
df['ts'] = pd.to_datetime(df['ts_iso'], errors='coerce', utc=True)
df['date'] = df['ts'].dt.date
print('Total rows:', len(df))
print('Date range:', df['ts'].min(), '->', df['ts'].max())
print()
print('--- per-day signal_rr stats ---')
for d, sub in df.groupby('date'):
    print(f'{d}  n={len(sub):6d}  max={sub.signal_rr.max():.3f}  p90={sub.signal_rr.quantile(0.90):.3f}  p95={sub.signal_rr.quantile(0.95):.3f}  p99={sub.signal_rr.quantile(0.99):.3f}  >=0.275: {(sub.signal_rr >= 0.275).sum()}  >=0.20: {(sub.signal_rr >= 0.20).sum()}')
