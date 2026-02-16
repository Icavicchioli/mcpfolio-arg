"""Unit tests for get_sector_peers tool."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


def _mock_sector_with_companies(symbols: list[str]) -> MagicMock:
    """Build a mock yf.Sector with a top_companies DataFrame."""
    df = pd.DataFrame(
        {"name": [f"{s} Inc" for s in symbols], "weight": [0.1] * len(symbols)},
        index=symbols,
    )
    mock_sector = MagicMock()
    mock_sector.top_companies = df
    return mock_sector


def test_get_sector_peers_success(finance_tools):
    """Test successful peer lookup with sector API available."""
    with patch("yfinance.Ticker") as mock_ticker_cls, patch("yfinance.Sector") as mock_sector_cls:
        mock_info = MagicMock()
        mock_info.info = {"sector": "Technology"}
        mock_ticker_cls.return_value = mock_info

        mock_sector_cls.return_value = _mock_sector_with_companies(
            ["MSFT", "NVDA", "GOOGL", "AMZN", "META", "AAPL"]
        )

        result = finance_tools["get_sector_peers"]("AAPL")

        assert result["ticker"] == "AAPL"
        assert result["sector"] == "Technology"
        # AAPL itself should be excluded from peers
        assert all(p["ticker"] != "AAPL" for p in result["peers"])
        assert result["count"] <= 5
        assert "error" not in result


def test_get_sector_peers_no_sector(finance_tools):
    """Test handling when ticker has no sector info."""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock = MagicMock()
        mock.info = {}
        mock_ticker_cls.return_value = mock

        result = finance_tools["get_sector_peers"]("AAPL")

        assert result["count"] == 0
        assert "error" in result


def test_get_sector_peers_sector_api_fallback(finance_tools):
    """Test that failures in yf.Sector return empty peers (not an exception)."""
    with (
        patch("yfinance.Ticker") as mock_ticker_cls,
        patch("yfinance.Sector", side_effect=Exception("API unavailable")),
    ):
        mock = MagicMock()
        mock.info = {"sector": "Technology"}
        mock_ticker_cls.return_value = mock

        result = finance_tools["get_sector_peers"]("AAPL")

        # Should return sector name but empty peer list — not crash
        assert result["ticker"] == "AAPL"
        assert result["sector"] == "Technology"
        assert result["peers"] == []
        assert "error" not in result


def test_get_sector_peers_ticker_uppercase(finance_tools):
    """Test ticker is normalized."""
    with patch("yfinance.Ticker") as mock_ticker_cls, patch("yfinance.Sector") as mock_sector_cls:
        mock = MagicMock()
        mock.info = {"sector": "Healthcare"}
        mock_ticker_cls.return_value = mock
        mock_sector_cls.return_value = _mock_sector_with_companies(["JNJ", "PFE"])

        result = finance_tools["get_sector_peers"]("aapl")
        assert result["ticker"] == "AAPL"
