"""Shared pytest fixtures for test suite"""

import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def mock_ticker_data():
    """Load mock ticker data from JSON fixture"""
    fixture_path = Path(__file__).parent / "fixtures" / "mock_ticker_data.json"
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def mock_news_data():
    """Load mock news data from JSON fixture"""
    fixture_path = Path(__file__).parent / "fixtures" / "mock_news_response.json"
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def mock_sentiment_data():
    """Load mock sentiment data from JSON fixture"""
    fixture_path = Path(__file__).parent / "fixtures" / "mock_sentiment.json"
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def mock_yfinance_ticker(mock_ticker_data):
    """Create a mock yfinance Ticker object"""

    def _create_mock(ticker_symbol="AAPL"):
        data = mock_ticker_data.get(ticker_symbol, mock_ticker_data["INVALID"])

        mock = Mock()
        mock.info = data["info"]

        # Create DataFrame for history
        hist_data = data["history"]
        if hist_data["dates"]:
            df = pd.DataFrame(
                {"High": hist_data["High"], "Low": hist_data["Low"], "Close": hist_data["Close"]},
                index=pd.to_datetime(hist_data["dates"]),
            )
        else:
            df = pd.DataFrame()

        mock.history.return_value = df

        return mock

    return _create_mock


@pytest.fixture
def mock_yfinance_ticker_with_news(mock_yfinance_ticker, mock_news_data):
    """Mock ticker with news data"""

    def _create_mock(ticker_symbol="AAPL"):
        mock = mock_yfinance_ticker(ticker_symbol)
        mock.news = mock_news_data
        return mock

    return _create_mock


@pytest.fixture
def mock_yfinance_ticker_with_sentiment(mock_yfinance_ticker, mock_sentiment_data):
    """Mock ticker with sentiment/recommendations data"""

    def _create_mock(ticker_symbol="AAPL"):
        mock = mock_yfinance_ticker(ticker_symbol)

        sentiment = mock_sentiment_data.get(ticker_symbol, [])
        df = pd.DataFrame(sentiment) if sentiment else pd.DataFrame()

        mock.recommendations = df
        return mock

    return _create_mock


@pytest.fixture
def mock_rate_limit_error():
    """Create a mock rate limit exception"""
    return Exception("Rate limit exceeded - 429 Too Many Requests")


@pytest.fixture
def mock_timeout_error():
    """Create a mock timeout exception"""
    return TimeoutError("Request timeout after 30 seconds")


@pytest.fixture
def sample_tickers():
    """Common test ticker symbols"""
    return {
        "valid": ["AAPL", "MSFT", "GOOGL", "AMZN"],
        "invalid": ["INVALID", "NOTREAL", ""],
        "funds": ["VTI", "SPY", "QQQ"],
    }


@pytest.fixture
def finance_tools():
    """Import finance tools and extract raw functions from FastMCP wrappers"""
    import server.finance as finance_mod

    # FastMCP stores the original function in .fn attribute
    return {
        "get_market_snapshot": (
            finance_mod.get_market_snapshot.fn
            if hasattr(finance_mod.get_market_snapshot, "fn")
            else finance_mod.get_market_snapshot
        ),
        "get_sentiment_data": (
            finance_mod.get_sentiment_data.fn
            if hasattr(finance_mod.get_sentiment_data, "fn")
            else finance_mod.get_sentiment_data
        ),
        "get_news": (
            finance_mod.get_news.fn if hasattr(finance_mod.get_news, "fn") else finance_mod.get_news
        ),
        "get_fund_info": (
            finance_mod.get_fund_info.fn
            if hasattr(finance_mod.get_fund_info, "fn")
            else finance_mod.get_fund_info
        ),
    }
