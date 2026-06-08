"""
Validation script: cross-check 30-day findings for robustness before live trading.
Checks DOWN bias, symbol performance, and time-of-day across weekly sub-periods.
"""
import pandas as pd
import numpy as np

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
df['week'] = df['ts'].dt.isocalendar().week

# Clean rows only
df = df[df['symbol'].isin(['BTCUSD','ETHUSD','SOLUSD','XRPUSD'])]
df = df[df['side'].isin(['UP','DOWN'])]

# -------------------------------------------------------
# 1. DOWN bias: is it consistent across all 4 weeks?
# -------------------------------------------------------
print('=' * 60)
print('CHECK 1: DOWN vs UP bias - by week')
print('=' * 60)
weeks = sorted(df['week'].unique())
for w in weeks:
    sub = df[df['week'] == w]
    dates = f"{sub['ts'].min().strftime('%m/%d')} - {sub['ts'].max().strftime('%m/%d')}"
    for side in ['DOWN','UP']:
        s = sub[sub['side'] == side]
        print(f"  Week {w} ({dates})  {side:4s}:  PnL={s['true_pnl'].sum():+7.2f}  Trades={len(s):4d}  Avg={s['true_pnl'].mean():+.4f}")
    print()

# -------------------------------------------------------
# 2. DOWN bias: is it driven by one leader or broad?
# -------------------------------------------------------
print('=' * 60)
print('CHECK 2: DOWN vs UP bias - by leader (top 8)')
print('=' * 60)
top_leaders = df.groupby('leader_address')['true_pnl'].sum().nlargest(8).index
for addr in top_leaders:
    sub = df[df['leader_address'] == addr]
    short = addr[:12]
    for side in ['DOWN','UP']:
        s = sub[sub['side'] == side]
        if len(s) > 0:
            print(f"  {short}  {side:4s}:  PnL={s['true_pnl'].sum():+7.2f}  Trades={len(s):4d}  Avg={s['true_pnl'].mean():+.4f}")
    print()

# -------------------------------------------------------
# 3. Symbol performance: consistent across weeks?
# -------------------------------------------------------
print('=' * 60)
print('CHECK 3: Symbol performance - by week')
print('=' * 60)
for w in weeks:
    sub = df[df['week'] == w]
    dates = f"{sub['ts'].min().strftime('%m/%d')} - {sub['ts'].max().strftime('%m/%d')}"
    print(f"  Week {w} ({dates}):")
    for sym in ['BTCUSD','ETHUSD','SOLUSD','XRPUSD']:
        s = sub[sub['symbol'] == sym]
        if len(s) > 0:
            print(f"    {sym}:  PnL={s['true_pnl'].sum():+7.2f}  Trades={len(s):4d}  Avg={s['true_pnl'].mean():+.4f}")
    print()

# -------------------------------------------------------
# 4. 04-08 UTC window: consistent across weeks?
# -------------------------------------------------------
print('=' * 60)
print('CHECK 4: 04-08 UTC window vs rest - by week')
print('=' * 60)
for w in weeks:
    sub = df[df['week'] == w]
    dates = f"{sub['ts'].min().strftime('%m/%d')} - {sub['ts'].max().strftime('%m/%d')}"
    peak = sub[sub['hour_utc'].between(4, 7)]
    rest = sub[~sub['hour_utc'].between(4, 7)]
    print(f"  Week {w} ({dates}):  04-08={peak['true_pnl'].sum():+.2f} ({len(peak)} trades)  rest={rest['true_pnl'].sum():+.2f} ({len(rest)} trades)")

# -------------------------------------------------------
# 5. Day of week: consistent?
# -------------------------------------------------------
print()
print('=' * 60)
print('CHECK 5: Day of week - by week')
print('=' * 60)
order = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
dow_week = df.groupby(['week','dow_name'])['true_pnl'].agg(['sum','count']).round(3)
dow_week.columns = ['PnL','Trades']
for w in weeks:
    sub = dow_week.loc[w] if w in dow_week.index else None
    if sub is not None:
        print(f"  Week {w}:")
        for day in order:
            if day in sub.index:
                row = sub.loc[day]
                print(f"    {day:10s}: PnL={row['PnL']:+7.3f}  Trades={int(row['Trades'])}")
    print()
