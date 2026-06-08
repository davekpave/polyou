"""Compare original-side vs contrarian-side EV on rr_blocks_resolved.csv.

Usage:
    python scripts/contrarian_analysis.py
    python scripts/contrarian_analysis.py --cutoff 2026-05-03

Without --cutoff: prints overall + per-bucket stats.
With --cutoff: splits rows into IN-SAMPLE (ts < cutoff) and OUT-OF-SAMPLE
(ts >= cutoff), prints headline numbers for both, so we can verify the edge
persists forward.

Per row:
- Original side: bot wanted to buy at snapshot_price; if won, P&L = (1-p); else -p.
- Contrarian:    buy the OTHER outcome at (1-p); if won, P&L = p; else -(1-p).
"""
import argparse
import pandas as pd


def add_pnl_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(subset=['snapshot_price', 'side', 'resolved_winner']).copy()
    df['snapshot_price'] = df['snapshot_price'].astype(float)
    df['orig_won'] = (df['side'] == df['resolved_winner']).astype(int)
    df['contra_won'] = 1 - df['orig_won']
    df['orig_pnl'] = df.apply(
        lambda r: (1.0 - r['snapshot_price']) if r['orig_won'] else -r['snapshot_price'],
        axis=1,
    )
    df['contra_entry'] = 1.0 - df['snapshot_price']
    df['contra_pnl'] = df.apply(
        lambda r: r['snapshot_price'] if r['contra_won'] else -(1.0 - r['snapshot_price']),
        axis=1,
    )
    return df


def headline(df: pd.DataFrame, label: str) -> None:
    n = len(df)
    print(f"\n--- {label}  (n={n}) ---")
    if n == 0:
        print("  (no rows)")
        return
    print(f"  date range:    {df['ts'].min()}  ->  {df['ts'].max()}")
    print(f"  ORIGINAL   WR={df['orig_won'].mean():.4f}  avg_pnl=${df['orig_pnl'].mean():+.4f}  total=${df['orig_pnl'].sum():+,.2f}")
    print(f"  CONTRARIAN WR={df['contra_won'].mean():.4f}  avg_pnl=${df['contra_pnl'].mean():+.4f}  total=${df['contra_pnl'].sum():+,.2f}")


def detail_breakdowns(df: pd.DataFrame) -> None:
    print("\nCONTRARIAN by entry-price band (1 - snapshot_price):")
    bands = [(0.0, 0.10), (0.10, 0.20), (0.20, 0.25), (0.25, 0.30), (0.30, 0.40), (0.40, 0.50)]
    print(f"  {'band':>14}  {'n':>6}  {'WR':>7}  {'avg_pnl':>9}  {'total_pnl':>12}")
    for lo, hi in bands:
        sub = df[(df['contra_entry'] >= lo) & (df['contra_entry'] < hi)]
        if len(sub) == 0:
            continue
        print(f"  [{lo:.2f}, {hi:.2f})  {len(sub):>6}  {sub['contra_won'].mean():>7.4f}  {sub['contra_pnl'].mean():>+9.4f}  ${sub['contra_pnl'].sum():>+11,.2f}")

    print("\nCONTRARIAN by symbol:")
    print(f"  {'symbol':>8}  {'n':>6}  {'WR':>7}  {'avg_pnl':>9}")
    for sym, sub in df.groupby('symbol'):
        print(f"  {sym:>8}  {len(sub):>6}  {sub['contra_won'].mean():>7.4f}  {sub['contra_pnl'].mean():>+9.4f}")

    df_rr = df.dropna(subset=['signal_rr']).copy()
    df_rr['signal_rr'] = df_rr['signal_rr'].astype(float)
    df_rr['rr_q'] = pd.qcut(df_rr['signal_rr'], 5, labels=['Q1', 'Q2', 'Q3', 'Q4', 'Q5'], duplicates='drop')
    print("\nCONTRARIAN by signal_rr quintile:")
    print(f"  {'rr_q':>4}  {'rr_range':>16}  {'n':>6}  {'WR':>7}  {'avg_pnl':>9}")
    for q, sub in df_rr.groupby('rr_q', observed=True):
        rng = f"[{sub['signal_rr'].min():.3f},{sub['signal_rr'].max():.3f}]"
        print(f"  {str(q):>4}  {rng:>16}  {len(sub):>6}  {sub['contra_won'].mean():>7.4f}  {sub['contra_pnl'].mean():>+9.4f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', default='logs/rr_blocks_resolved.csv')
    ap.add_argument('--cutoff', help='ISO date YYYY-MM-DD; rows >= cutoff are out-of-sample.')
    args = ap.parse_args()

    df = pd.read_csv(args.csv, on_bad_lines='skip', engine='python')
    df['ts'] = pd.to_datetime(df['ts_iso'], errors='coerce', utc=True)
    df = add_pnl_columns(df)

    if args.cutoff:
        cutoff = pd.Timestamp(args.cutoff, tz='UTC')
        in_sample = df[df['ts'] < cutoff]
        oos = df[df['ts'] >= cutoff]
        headline(in_sample, f"IN-SAMPLE (ts < {args.cutoff})")
        headline(oos, f"OUT-OF-SAMPLE (ts >= {args.cutoff})")
        if len(oos) > 100:
            print()
            print("=" * 70)
            print("OUT-OF-SAMPLE breakdown")
            print("=" * 70)
            detail_breakdowns(oos)
    else:
        headline(df, "ALL ROWS")
        print()
        detail_breakdowns(df)


if __name__ == '__main__':
    main()
