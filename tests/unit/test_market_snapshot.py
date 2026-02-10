"""Unit tests for get_market_snapshot tool"""

from unittest.mock import Mock, patch

import pandas as pd


def test_get_market_snapshot_success(finance_tools, mock_yfinance_ticker):
    """Test successful market snapshot retrieval"""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value = mock_yfinance_ticker("AAPL")

        result = finance_tools["get_market_snapshot"]("AAPL")

        assert result["ticker"] == "AAPL"
        assert result["current_price"] == 153.25
        assert result["volume"] == 50234100
        assert result["high_52_week"] == 180.0
        assert result["low_52_week"] == 145.0
        assert "volatility_52_week_pct" in result
        assert result["volatility_52_week_pct"] > 0
        assert "error" not in result


def test_get_market_snapshot_invalid_ticker(finance_tools, mock_yfinance_ticker):
    """Test invalid ticker handling"""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value = mock_yfinance_ticker("INVALID")

        result = finance_tools["get_market_snapshot"]("INVALID")

        assert result["error"]
        assert result["error_type"] == "invalid_ticker"
        assert result["ticker"] == "INVALID"


def test_get_market_snapshot_empty_ticker(finance_tools):
    """Test empty ticker validation"""
    result = finance_tools["get_market_snapshot"]("")

    # Should handle gracefully - empty string is stripped
    assert result["ticker"] == ""


def test_get_market_snapshot_no_historical_data(finance_tools):
    """Test handling when no historical data available"""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock = Mock()
        mock.info = {"symbol": "TEST", "currentPrice": 100.0}
        mock.history.return_value = pd.DataFrame()  # Empty DataFrame
        mock_ticker_cls.return_value = mock

        result = finance_tools["get_market_snapshot"]("TEST")

        assert result["error"]
        assert result["error_type"] == "no_data"


def test_get_market_snapshot_rate_limit(finance_tools, mock_rate_limit_error):
    """Test rate limit error handling"""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_ticker_cls.side_effect = mock_rate_limit_error

        result = finance_tools["get_market_snapshot"]("AAPL")

        assert result["error"]
        assert result["error_type"] == "rate_limit"
        assert "retry" in result["error"].lower() or "limit" in result["error"].lower()


def test_get_market_snapshot_timeout(finance_tools, mock_timeout_error):
    """Test timeout error handling"""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_ticker_cls.side_effect = mock_timeout_error

        result = finance_tools["get_market_snapshot"]("AAPL")

        assert result["error"]
        assert result["error_type"] == "unknown"


def test_get_market_snapshot_ticker_case_insensitive(finance_tools, mock_yfinance_ticker):
    """Test ticker is converted to uppercase"""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value = mock_yfinance_ticker("AAPL")

        result = finance_tools["get_market_snapshot"]("aapl")  # lowercase

        assert result["ticker"] == "AAPL"  # Should be uppercase


def test_get_market_snapshot_volatility_calculation(finance_tools, mock_yfinance_ticker):
    """Test volatility calculation is correct"""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value = mock_yfinance_ticker("AAPL")

        result = finance_tools["get_market_snapshot"]("AAPL")

        # Volatility should be calculated as (high - low) / low * 100
        expected_volatility = ((180.0 - 145.0) / 145.0) * 100
        assert abs(result["volatility_52_week_pct"] - expected_volatility) < 0.1


def test_get_market_snapshot_optional_fields(finance_tools):
    """Test handling of optional fields (calendar, analyst targets, etc.)"""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock = Mock()
        mock.info = {"symbol": "TEST", "currentPrice": 100.0, "regularMarketVolume": 1000000}
        mock.history.return_value = pd.DataFrame(
            {"High": [110.0, 105.0], "Low": [95.0, 90.0], "Close": [100.0, 98.0]},
            index=pd.to_datetime(["2025-01-01", "2025-02-01"]),
        )

        # These fields might not exist
        mock.calendar = None
        mock.analyst_price_targets = None
        mock.quarterly_income_stmt = None

        mock_ticker_cls.return_value = mock

        result = finance_tools["get_market_snapshot"]("TEST")

        # Should succeed even without optional fields
        assert "error" not in result
        assert result["ticker"] == "TEST"
