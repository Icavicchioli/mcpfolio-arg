"""Unit tests for get_earnings_calendar tool."""

import sys
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


def test_get_earnings_calendar_with_upcoming_date(finance_tools):
    """Test earnings calendar with a valid upcoming date."""
    from datetime import date, timedelta

    future_date = date.today() + timedelta(days=30)

    with patch("yfinance.Ticker") as mock_cls:
        mock = Mock()
        mock.calendar = {
            "Earnings Date": [future_date],
            "Earnings Average": 2.45,
            "Revenue Average": 90_000_000_000,
        }
        mock_cls.return_value = mock

        result = finance_tools["get_earnings_calendar"]("AAPL")

        assert result["ticker"] == "AAPL"
        assert result["earnings_date"] == str(future_date)
        assert result["days_until_earnings"] == 30
        assert result["eps_estimate"] == 2.45
        assert result["earnings_imminent"] is False
        assert "error" not in result


def test_get_earnings_calendar_imminent(finance_tools):
    """Test that earnings within 7 days sets earnings_imminent=True."""
    from datetime import date, timedelta

    close_date = date.today() + timedelta(days=3)

    with patch("yfinance.Ticker") as mock_cls:
        mock = Mock()
        mock.calendar = {"Earnings Date": [close_date], "Earnings Average": 1.85}
        mock_cls.return_value = mock

        result = finance_tools["get_earnings_calendar"]("MSFT")

        assert result["earnings_imminent"] is True
        assert result["days_until_earnings"] == 3


def test_get_earnings_calendar_no_data(finance_tools):
    """Test handling when no calendar is available."""
    with patch("yfinance.Ticker") as mock_cls:
        mock = Mock()
        mock.calendar = None
        mock_cls.return_value = mock

        result = finance_tools["get_earnings_calendar"]("AAPL")

        assert "error" in result
        assert result["error_type"] == "no_data"


def test_get_earnings_calendar_ticker_uppercase(finance_tools):
    """Test ticker is normalized to uppercase."""
    from datetime import date, timedelta

    with patch("yfinance.Ticker") as mock_cls:
        mock = Mock()
        mock.calendar = {"Earnings Date": [date.today() + timedelta(days=10)]}
        mock_cls.return_value = mock

        result = finance_tools["get_earnings_calendar"]("aapl")
        assert result["ticker"] == "AAPL"
