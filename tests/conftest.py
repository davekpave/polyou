"""
Pytest configuration and shared fixtures.
"""
import pytest
import sys
from pathlib import Path

# Add src to path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))


@pytest.fixture
def sample_spot_price_event():
    """Create a sample SpotPriceEvent for testing."""
    from polyou.core.data import SpotPriceEvent
    return SpotPriceEvent(
        symbol="BTCUSD",
        price=50000.0,
        ts=1704067200.0  # 2024-01-01 00:00:00 UTC
    )


@pytest.fixture
def market_data():
    """Create a MarketData instance for testing."""
    from polyou.core.data import MarketData
    return MarketData()
