"""Unit tests for get_news tool"""

from unittest.mock import patch


def test_get_news_success(finance_tools, mock_yfinance_ticker_with_news):
    """Test successful news retrieval"""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value = mock_yfinance_ticker_with_news("AAPL")

        result = finance_tools["get_news"]("AAPL", count=10)

        assert result["ticker"] == "AAPL"
        assert "news" in result
        assert result["count"] > 0
        assert len(result["news"]) <= 10
        assert "error" not in result

        # Check article structure
        for article in result["news"]:
            assert "title" in article
            assert "publisher" in article
            assert "link" in article
            assert "published_date" in article


def test_get_news_no_articles(finance_tools, mock_yfinance_ticker):
    """Test handling when no news articles available"""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock = mock_yfinance_ticker("AAPL")
        mock.news = []  # No news
        mock_ticker_cls.return_value = mock

        result = finance_tools["get_news"]("AAPL")

        assert result["ticker"] == "AAPL"
        assert result["news"] == []
        assert result["count"] == 0


def test_get_news_with_date_filter(finance_tools, mock_yfinance_ticker_with_news):
    """Test date filtering"""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_ticker_cls.return_value = mock_yfinance_ticker_with_news("AAPL")

        result = finance_tools["get_news"]("AAPL", count=10, date="2026-02-01")

        assert result["ticker"] == "AAPL"
        assert result["filtered_by_date"] == "2026-02-01"


def test_get_news_invalid_date_format(finance_tools):
    """Test invalid date format handling"""
    result = finance_tools["get_news"]("AAPL", date="02/01/2026")  # Wrong format

    assert result["error"]
    assert result["error_type"] == "invalid_date"


def test_get_news_rate_limit(finance_tools, mock_rate_limit_error):
    """Test rate limit error handling"""
    with patch("yfinance.Ticker") as mock_ticker_cls:
        mock_ticker_cls.side_effect = mock_rate_limit_error

        result = finance_tools["get_news"]("AAPL")

        assert result["error"]
        assert result["error_type"] == "rate_limit"
