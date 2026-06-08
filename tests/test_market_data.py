"""
Unit tests for the MarketData class.
"""
import pytest
from polyou.core.data import MarketData, SpotPriceEvent


class TestMarketData:
    """Test cases for MarketData class."""

    def test_initialization(self):
        """Test that MarketData initializes with empty state."""
        md = MarketData()
        assert md.get_replay("BTCUSD") == []
        assert md.get_anchor_windows("BTCUSD") == []

    def test_add_price_via_on_message(self, market_data):
        """Test that adding a price creates a replay buffer for the symbol."""
        event = SpotPriceEvent(
            symbol="BTCUSD",
            price=50000.0,
            ts=1704067200.0
        )
        market_data.on_message(event)
        
        replay = market_data.get_replay("BTCUSD")
        assert len(replay) == 1
        assert replay[0].symbol == "BTCUSD"
        assert replay[0].price == 50000.0

    def test_add_multiple_prices(self, market_data):
        """Test adding multiple price events for the same symbol."""
        events = [
            SpotPriceEvent(symbol="BTCUSD", price=50000.0, ts=1704067200.0),
            SpotPriceEvent(symbol="BTCUSD", price=50100.0, ts=1704067201.0),
            SpotPriceEvent(symbol="BTCUSD", price=50200.0, ts=1704067202.0),
        ]
        
        for event in events:
            market_data.on_message(event)
        
        replay = market_data.get_replay("BTCUSD")
        assert len(replay) == 3
        assert replay[-1].price == 50200.0

    def test_replay_buffer_max_length(self, market_data):
        """Test that replay buffer respects maximum length (500)."""
        # Add 600 events
        for i in range(600):
            event = SpotPriceEvent(symbol="BTCUSD", price=50000.0 + i, ts=1704067200.0 + i)
            market_data.on_message(event)
        
        # Should only keep the last 500
        replay = market_data.get_replay("BTCUSD")
        assert len(replay) == 500
        # First price should be from index 100 (600-500)
        assert replay[0].price == 50100.0

    def test_get_replay_size(self, market_data):
        """Test getting the replay buffer size."""
        for i in range(10):
            event = SpotPriceEvent(symbol="BTCUSD", price=50000.0 + i, ts=1704067200.0 + i)
            market_data.on_message(event)
        
        assert market_data.get_replay_size("BTCUSD") == 10

    def test_has_min_replay(self, market_data):
        """Test checking for minimum replay data."""
        for i in range(5):
            event = SpotPriceEvent(symbol="BTCUSD", price=50000.0, ts=1704067200.0 + i)
            market_data.on_message(event)
        
        assert market_data.has_min_replay("BTCUSD", 5)
        assert not market_data.has_min_replay("BTCUSD", 10)

    def test_get_latest_spot(self, market_data):
        """Test getting the most recent spot price."""
        events = [
            SpotPriceEvent(symbol="BTCUSD", price=50000.0, ts=1704067200.0),
            SpotPriceEvent(symbol="BTCUSD", price=50500.0, ts=1704067201.0),
        ]
        
        for event in events:
            market_data.on_message(event)
        
        latest = market_data.get_latest_spot("BTCUSD")
        assert latest is not None
        assert latest.price == 50500.0

    def test_get_latest_spot_empty(self, market_data):
        """Test get_latest_spot for a symbol with no data."""
        latest = market_data.get_latest_spot("ETHUSD")
        assert latest is None

    def test_set_anchor(self, market_data):
        """Test setting a window anchor price."""
        market_data.set_anchor(symbol="BTCUSD", window_start_ts=1704067200, price=50000.0)
        
        anchor = market_data.get_anchor(symbol="BTCUSD", window_start_ts=1704067200)
        assert anchor == 50000.0

    def test_get_anchor(self, market_data):
        """Test retrieving a window anchor."""
        market_data.set_anchor(symbol="BTCUSD", window_start_ts=1704067200, price=50000.0)
        
        anchor = market_data.get_anchor(symbol="BTCUSD", window_start_ts=1704067200)
        assert anchor == 50000.0

    def test_get_anchor_missing(self, market_data):
        """Test getting anchor for non-existent window returns None."""
        anchor = market_data.get_anchor(symbol="BTCUSD", window_start_ts=1704067200)
        assert anchor is None

    def test_get_anchor_windows(self, market_data):
        """Test getting list of anchor windows."""
        market_data.set_anchor(symbol="BTCUSD", window_start_ts=1704067200, price=50000.0)
        market_data.set_anchor(symbol="BTCUSD", window_start_ts=1704068100, price=50500.0)
        
        windows = market_data.get_anchor_windows("BTCUSD")
        assert windows == [1704067200, 1704068100]

    def test_multiple_symbols(self, market_data):
        """Test handling multiple symbols independently."""
        btc_event = SpotPriceEvent(symbol="BTCUSD", price=50000.0, ts=1704067200.0)
        eth_event = SpotPriceEvent(symbol="ETHUSD", price=3000.0, ts=1704067200.0)
        
        market_data.on_message(btc_event)
        market_data.on_message(eth_event)
        
        btc_replay = market_data.get_replay("BTCUSD")
        eth_replay = market_data.get_replay("ETHUSD")
        
        assert len(btc_replay) == 1
        assert len(eth_replay) == 1
        assert btc_replay[0].price == 50000.0
        assert eth_replay[0].price == 3000.0

    def test_is_stable_insufficient_data(self, market_data):
        """Test stability check with insufficient data."""
        # No data should return False for legacy mode
        is_stable = market_data.is_stable("BTCUSD", seconds=180)
        assert not is_stable

    def test_anchor_event_via_on_message(self, market_data):
        """Test that anchor events can be set via on_message."""
        anchor_event = {
            "type": "ANCHOR_PRICE",
            "symbol": "BTCUSD",
            "window_start_ts": 1704067200,
            "price": 50000.0
        }
        
        market_data.on_message(anchor_event)
        
        anchor = market_data.get_anchor(symbol="BTCUSD", window_start_ts=1704067200)
        assert anchor == 50000.0

