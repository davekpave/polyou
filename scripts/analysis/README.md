# Analysis Scripts

This directory contains scripts for analyzing trading performance, strategy effectiveness, and market behavior.

## Scripts

### Performance Analysis
- **`analyze_winrate.py`** — Calculate win rates across different conditions
- **`analyze_winners_losers.py`** — Identify winning and losing patterns
- **`analyze_up_vs_down.py`** — Compare UP vs DOWN position performance
- **`analyze_eth_vs_btc.py`** — Compare ETH vs BTC market performance

### Strategy Comparison
- **`compare_strategies.py`** — Compare different trading strategies
- **`compare_price_sources.py`** — Compare different price data sources (Chainlink, Kraken, CoinGecko)
- **`compare_original_vs_current.py`** — Compare current strategy against historical baseline

## Usage

These scripts typically read from:
- `logs/execution_log.csv` — Trade execution history
- `logs/exit_log.csv` — Position exit data
- `active_positions.json` — Current open positions

Run from the workspace root:
```bash
python scripts/analysis/analyze_winrate.py
```

## Output

Scripts may output:
- CSV reports
- Console statistics
- Charts/visualizations (if matplotlib installed)

## Adding New Analysis

When creating new analysis scripts:
1. Use pandas for data manipulation
2. Include clear output formatting
3. Add date range filtering where appropriate
4. Document assumptions and methodology
