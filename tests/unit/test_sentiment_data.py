"""Unit tests for get_sentiment_data tool"""

from unittest.mock import patch


def test_get_sentiment_data_success(finance_tools, mock_yfinance_ticker_with_sentiment):
    """Test successful sentiment data retrieval"""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value = mock_yfinance_ticker_with_sentiment("AAPL")

        result = finance_tools["get_sentiment_data"]("AAPL", count=5)

        assert result["ticker"] == "AAPL"
        assert "ratings" in result
        assert result["count"] > 0
        assert len(result["ratings"]) <= 5
        assert "error" not in result


def test_get_sentiment_data_no_ratings(finance_tools, mock_yfinance_ticker):
    """Test handling when no analyst ratings available"""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock = mock_yfinance_ticker("AAPL")
        mock.recommendations = None  # No recommendations
        mock_ticker_cls.return_value = mock

        result = finance_tools["get_sentiment_data"]("AAPL")

        assert result["ticker"] == "AAPL"
        assert result["ratings"] == []
        assert result["count"] == 0
        assert "message" in result


def test_get_sentiment_data_rate_limit(finance_tools, mock_rate_limit_error):
    """Test rate limit error handling"""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_ticker_cls.side_effect = mock_rate_limit_error

        result = finance_tools["get_sentiment_data"]("AAPL")

        assert result["error"]
        assert result["error_type"] == "rate_limit"


def test_get_sentiment_data_ticker_uppercase(finance_tools, mock_yfinance_ticker_with_sentiment):
    """Test ticker is converted to uppercase"""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value = mock_yfinance_ticker_with_sentiment("MSFT")

        result = finance_tools["get_sentiment_data"]("msft")  # lowercase

        assert result["ticker"] == "MSFT"
