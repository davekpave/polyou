# Tests

This directory contains the test suite for the Polyou trading bot.

## Running Tests

Run all tests:
```bash
pytest
```

Run with verbose output:
```bash
pytest -v
```

Run specific test file:
```bash
pytest tests/test_market_data.py -v
```

Run tests matching a pattern:
```bash
pytest -k "test_anchor" -v
```

## Test Structure

- **`conftest.py`** — Shared fixtures for all tests
- **`test_market_data.py`** — Unit tests for the MarketData class (15 tests)
- **`test_polyou_bot.py`** — Concept tests for bot logic, gates, and signal calculations (11 tests)
- **`test_execution_client.py`** — Tests for execution client concepts (6 tests)

## Current Coverage

The test suite currently has **32 tests** covering:

### MarketData Core Functionality ✅
- Event ingestion via `on_message()`
- Replay buffer management (max 500 events)
- Window anchor storage and retrieval
- Multi-symbol handling
- Stability checks

### Signal Calculation Concepts ✅
- Distance from anchor calculations
- Z-score normalization
- Volatility ratio calculations
- Quality score bounds
- Division-by-zero protection

### Position Sizing Logic ✅
- Tiered sizing by quality
- Minimum and maximum position limits

### Execution Concepts ✅
- Order deduplication
- Balance checks
- State persistence
- Retry logic
- Rounding behavior

## Next Steps for Testing

To reach production-grade coverage, consider adding:

1. **Integration tests** — Test bot with mocked CLOB client and real market data
2. **Gate logic tests** — Test the 12+ gates in `polyou_bot.py` with real data scenarios
3. **Edge case tests** — Test error conditions, network failures, malformed data
4. **Performance tests** — Test memory usage over long runs, cleanup behavior
5. **Polymarket resolver tests** — Test token ID resolution and slug building
6. **Chainlink poller tests** — Test price feed fallback logic

## Test Requirements

Install test dependencies:
```bash
pip install -r requirements.txt
```

Key packages:
- `pytest==9.0.2` — Test framework
- All production dependencies (needed to import source modules)

## Notes

- Tests use the actual source code from `src/polyou/`
- Some tests are "concept tests" that validate logic patterns without requiring full bot initialization
- Tests avoid requiring live API credentials or network access
- Sensitive configuration (`.env` files, JSON state) is not needed for unit tests
