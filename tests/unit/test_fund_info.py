"""Unit tests for get_fund_info tool"""

from unittest.mock import Mock, patch

import pandas as pd


def test_get_fund_info_success(finance_tools):
    """Test successful fund info retrieval"""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock = Mock()

        # Mock funds_data object
        funds_data = Mock()
        funds_data.fund_overview = {"fundFamily": "Vanguard", "category": "Large Blend"}
        funds_data.top_holdings = pd.DataFrame(
            {"symbol": ["AAPL", "MSFT", "GOOGL"], "holdingPercent": [5.2, 4.8, 3.9]}
        )
        funds_data.sector_weightings = {"Technology": 28.5, "Healthcare": 15.3}

        mock.funds_data = funds_data
        mock_ticker_cls.return_value = mock

        result = finance_tools["get_fund_info"]("VTI")

        assert result["ticker"] == "VTI"
        assert result["fund_overview"] is not None
        assert result["top_holdings"] is not None
        assert len(result["top_holdings"]) == 3
        assert result["sector_weightings"] is not None
        assert "error" not in result


def test_get_fund_info_no_data(finance_tools):
    """Test handling when ticker is not a fund"""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock = Mock()
        mock.funds_data = None  # Not a fund
        mock_ticker_cls.return_value = mock

        result = finance_tools["get_fund_info"]("AAPL")  # Regular stock, not a fund

        assert result["error"]
        assert result["error_type"] == "no_data"
        assert "fund" in result["error"].lower()


def test_get_fund_info_rate_limit(finance_tools, mock_rate_limit_error):
    """Test rate limit error handling"""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_ticker_cls.side_effect = mock_rate_limit_error

        result = finance_tools["get_fund_info"]("VTI")

        assert result["error"]
        assert result["error_type"] == "rate_limit"


def test_get_fund_info_ticker_uppercase(finance_tools):
    """Test ticker is converted to uppercase"""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock = Mock()
        mock.funds_data = None
        mock_ticker_cls.return_value = mock

        result = finance_tools["get_fund_info"]("vti")  # lowercase

        assert result["ticker"] == "VTI"
