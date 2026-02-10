"""Integration tests for MCP server"""

import sys
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.mark.integration
def test_mcp_server_imports():
    """Test MCP server can be imported"""
    from server import finance

    assert hasattr(finance, "get_market_snapshot")
    assert hasattr(finance, "get_sentiment_data")
    assert hasattr(finance, "get_news")
    assert hasattr(finance, "get_fund_info")


@pytest.mark.integration
def test_all_tools_have_correct_signature(finance_tools):
    """Test all tools have correct function signatures"""
    import inspect

    # Check get_market_snapshot
    sig = inspect.signature(finance_tools["get_market_snapshot"])
    assert "ticker" in sig.parameters

    # Check get_sentiment_data
    sig = inspect.signature(finance_tools["get_sentiment_data"])
    assert "ticker" in sig.parameters
    assert "count" in sig.parameters

    # Check get_news
    sig = inspect.signature(finance_tools["get_news"])
    assert "ticker" in sig.parameters
    assert "count" in sig.parameters
    assert "date" in sig.parameters

    # Check get_fund_info
    sig = inspect.signature(finance_tools["get_fund_info"])
    assert "ticker" in sig.parameters


@pytest.mark.integration
def test_tool_return_types(finance_tools):
    """Test all tools return dictionaries"""
    from unittest.mock import Mock, patch

    with patch("yfinance.Ticker") as mock_ticker:
        mock = Mock()
        mock.info = {}
        mock.history.return_value = Mock(empty=True)
        mock_ticker.return_value = mock

        result = finance_tools["get_market_snapshot"]("INVALID")

        assert isinstance(result, dict)
        assert "ticker" in result


@pytest.mark.integration
def test_error_structure_consistency(finance_tools):
    """Test all tools return consistent error structure"""
    from unittest.mock import patch

    with patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.side_effect = Exception("Test error")

        # Test all tools return same error structure
        for tool_name in ["get_market_snapshot", "get_sentiment_data", "get_news", "get_fund_info"]:
            result = finance_tools[tool_name]("TEST")

            assert "error" in result
            assert "ticker" in result
            assert "error_type" in result
            assert result["error_type"] in ["invalid_ticker", "no_data", "rate_limit", "unknown"]
