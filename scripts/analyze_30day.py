import pandas as pd

df = pd.read_csv('logs/shadow_exits.csv', names=[
    'ts_iso','position_id','leader_address','token_id','symbol','side',
    'entry_price','entry_ts','exit_ts','exit_type','exit_price',
    'profit_per_share','best_ask_at_exit','best_bid_at_exit','spread_bps_at_exit',
    'clob_age_ms_at_exit','window_end_ts','hold_seconds','snapshot_price',
    'slippage_vs_snapshot','signal_rr','signal_quality','signal_priority',
    'contract_slug','predicted_side_won','inverse_pnl_naive','inverse_pnl_3c_spread',
    'window_start_price','window_end_price','actual_won','true_pnl','true_inverse_pnl'
])
df = df[df['ts_iso'] != 'ts_iso']
df['ts'] = pd.to_datetime(df['ts_iso'], format='ISO8601', utc=True)
df['true_pnl'] = pd.to_numeric(df['true_pnl'], errors='coerce')
df['hour_utc'] = df['ts'].dt.hour
df['dow_name'] = df['ts'].dt.day_name()

# Clean rows only
df2 = df[df['symbol'].isin(['BTCUSD','ETHUSD','SOLUSD','XRPUSD'])]
df2 = df2[df2['side'].isin(['UP','DOWN'])]
print(f'Clean trades: {len(df2)}')

print('\n=== BY SYMBOL ===')
sym = df2.groupby('symbol')['true_pnl'].agg(['sum','count','mean']).round(4)
sym.columns = ['Total_PnL', 'Trades', 'Avg_Trade']
print(sym.sort_values('Total_PnL', ascending=False).to_string())

print('\n=== BY SIDE ===')
side = df2.groupby('side')['true_pnl'].agg(['sum','count','mean']).round(4)
side.columns = ['Total_PnL', 'Trades', 'Avg_Trade']
print(side.to_string())

print('\n=== BY SYMBOL + SIDE ===')
ss = df2.groupby(['symbol','side'])['true_pnl'].agg(['sum','count','mean']).round(4)
ss.columns = ['Total_PnL', 'Trades', 'Avg_Trade']
print(ss.sort_values('Total_PnL', ascending=False).to_string())

print('\n=== BY DAY OF WEEK ===')
dow = df2.groupby('dow_name')['true_pnl'].agg(['sum','count','mean']).round(4)
dow.columns = ['Total_PnL', 'Trades', 'Avg_Trade']
order = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
print(dow.reindex([d for d in order if d in dow.index]).to_string())

print('\n=== BY 4-HOUR BLOCK (UTC) ===')
blocks = [(0,4,'00-04'),(4,8,'04-08'),(8,12,'08-12'),(12,16,'12-16'),(16,20,'16-20'),(20,24,'20-24')]
for start, end, label in blocks:
    sub = df2[df2['hour_utc'].between(start, end-1)]
    pnl = sub['true_pnl'].sum()
    cnt = len(sub)
    avg = sub['true_pnl'].mean() if cnt > 0 else 0
    print(f'{label} UTC:  PnL={pnl:+.3f}  Trades={cnt}  Avg={avg:.4f}')

print('\n=== BY HOUR (UTC) ===')
hour = df2.groupby('hour_utc')['true_pnl'].agg(['sum','count','mean']).round(4)
hour.columns = ['Total_PnL', 'Trades', 'Avg_Trade']
print(hour.to_string())
