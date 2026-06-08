# Utility Scripts

This directory contains operational scripts for managing positions, redemptions, and blockchain interactions.

## Scripts

### Position Management
- **`manage_positions.py`** — Interactive position management (view, close, adjust)
- **`close_stuck_position.py`** — Force-close positions that failed to auto-close

### Token Operations
- **`approve_usdc.py`** — Approve USDC spending for the CLOB contract
- **`redeem_winnings.py`** — Redeem winning positions for USDC
- **`redeem_all.py`** — Batch redeem all redeemable positions

## Usage

### Approve USDC (First Time Setup)
```bash
python scripts/utils/approve_usdc.py
```
Required before placing first order. Approves USDC spending on Polygon.

### Redeem Winnings
```bash
# Redeem specific positions
python scripts/utils/redeem_winnings.py

# Redeem all eligible positions
python scripts/utils/redeem_all.py
```

### Close Stuck Positions
```bash
python scripts/utils/close_stuck_position.py
```
Useful when a position didn't auto-close due to:
- Bot downtime during settlement
- Network issues
- Failed exit transaction

### Manage Positions Interactively
```bash
python scripts/utils/manage_positions.py
```
Provides an interactive menu to:
- View open positions
- Close positions manually
- Check position status
- View estimated P&L

## Requirements

All scripts require:
- `.env` file with `POLY_PRIVATE_KEY`
- Active internet connection
- Polygon RPC access (for on-chain operations)

## Safety Notes

- **Always verify position details** before closing manually
- **Check gas prices** before approving large amounts
- **Redemptions are final** — ensure settlement has occurred
- **Test with small amounts** first when using new scripts

## Gas Costs

Approximate gas costs (as of 2026):
- USDC approval: ~$0.10-0.30
- Close position: ~$0.20-0.50
- Redeem winnings: ~$0.15-0.40

Costs vary with Polygon network congestion.
