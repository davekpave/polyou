# Debug Scripts

This directory contains ad-hoc scripts used for testing, debugging, and exploration during development.

## Categories

### Testing & Debugging (`test_*.py`)
Quick tests for specific components or API interactions:
- `test_bal.py`, `test_bal2.py` — Balance checking tests
- `test_chainlink_*.py` — Chainlink integration tests
- `test_clob.py`, `clob_test.py` — CLOB API testing
- `test_decision_email.py`, `test_observation_email.py` — Email notification tests
- `test_fok.py`, `test_post_fok.py` — Fill-or-Kill order tests
- `test_get_order_hist.py` — Order history retrieval
- `test_match*.py` — Market matching tests
- `test_order*.py` — Order placement and debugging
- `test_w3.py`, `test_ws.py` — Web3 and WebSocket tests

### Data Inspection (`check_*.py`, `inspect_*.py`, `get_*.py`)
Scripts for examining live data and state:
- `check_balances.py` — View wallet balances
- `check_current_anchors.py` — Inspect oracle anchor prices
- `check_internal_wallets.py` — Wallet state verification
- `check_prices.py` — Price feed inspection
- `check_trades.py`, `check_two_trades.py` — Trade history review
- `check_tx*.py` — Transaction inspection
- `get_ctf_balance.py` — CTF token balance retrieval
- `get_historical_prices.py` — Historical price data
- `get_trades.py` — Trade data extraction
- `inspect_gamma.py` — Gamma API inspection
- `inspect_order_response.py` — Order response debugging

### API Exploration (`probe_*.py`, `investigate_*.py`, `research_*.py`)
Scripts for exploring external APIs and data sources:
- `probe_alt_price.py`, `probe_chainlink.py` — Price feed exploration
- `investigate_chainlink_api.py` — Chainlink API investigation
- `research_chainlink_access.py` — Chainlink access patterns
- `chainlink_stream_query*.py` — Chainlink stream query testing

### Utilities (`print_*.py`, `parse_*.py`, `patch_*.py`)
Miscellaneous debugging helpers:
- `print_resp*.py` — Response debugging
- `parse_mass*.py` — Bulk data parsing
- `patch_bot.py`, `patch_client.py` — Hot-patching experiments
- `temp.py`, `new.py` — Temporary/scratch files

### Internal Tools (`_*.py`)
Internal analysis and monitoring:
- `_analyze.py` — Ad-hoc analysis
- `_status.py` — Status checking
- `_timing*.py` — Performance timing

## Usage

These scripts are not part of the production bot. They were created for:
- Quick API experimentation
- Debugging specific issues
- Data exploration
- One-off analysis

Most require environment variables (`.env` file) and may need updates to work with current codebase.

## Maintenance

When creating new debug scripts, consider:
1. Using descriptive names that indicate purpose
2. Adding a comment at the top explaining what the script does
3. Cleaning up or deleting scripts once the issue is resolved
4. Moving frequently-used scripts to proper modules in `src/`
