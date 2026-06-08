# Audit Scripts

This directory contains scripts for auditing trading outcomes and verifying position settlements.

## Scripts

### Trade Auditing
- **`audit_actual.py`** — Audit actual trade outcomes vs expected
- **`audit_outcomes.py`** — Verify settlement outcomes against oracle data
- **`audit_today.py`** — Quick audit of today's trades

### Win Verification
- **`check_actual_wins.py`** — Check actual winning positions
- **`check_real_wins.py`** — Verify real P&L from settled positions

## Purpose

These scripts help ensure:
- Trades settle correctly based on oracle prices
- P&L calculations are accurate
- No discrepancies between expected and actual outcomes
- Oracle price anchors match Chainlink settlement values

## Data Sources

Scripts typically read from:
- `logs/execution_log.csv` — Entry positions
- `logs/exit_log.csv` — Exit records
- Polymarket CLOB API — Position status
- Chainlink on-chain data — Settlement prices

## Usage

Run from workspace root:
```bash
python scripts/audit/audit_today.py
```

Most scripts will output:
- Mismatches between expected and actual outcomes
- Settlement discrepancies
- P&L summaries

## When to Run

- After market windows settle (15 minutes after window close)
- When investigating unexpected losses
- For daily reconciliation
- Before rebalancing positions
