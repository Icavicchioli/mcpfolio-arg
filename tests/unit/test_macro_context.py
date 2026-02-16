"""Unit tests for get_macro_context tool."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


def _make_price_history(prices: list[float]) -> pd.DataFrame:
    import pandas as pd

    dates = pd.date_range("2026-01-01", periods=len(prices), freq="D")
    return pd.DataFrame(
        {"Close": prices, "Open": prices, "High": prices, "Low": prices}, index=dates
    )


def test_get_macro_context_success(finance_tools):
    """Test successful macro context retrieval."""
    with patch("yfinance.Ticker") as mock_cls:

        def make_ticker(sym):
            mock = MagicMock()
            if sym == "^GSPC":
                mock.history.return_value = _make_price_history([4500.0, 4600.0])
            elif sym == "^VIX":
                mock.history.return_value = _make_price_history([18.5])
            elif sym == "^TNX":
                mock.history.return_value = _make_price_history([4.25])
            return mock

        mock_cls.side_effect = make_ticker

        result = finance_tools["get_macro_context"]()

        assert "error" not in result
        assert result["sp500_ytd_pct"] is not None
        assert result["vix_level"] == 18.5
        assert result["market_regime"] == "Normal"
        assert result["treasury_10y_yield"] == 4.25


def test_get_macro_context_vix_regimes(finance_tools):
    """Test that VIX level maps to correct market regime."""
    import server.finance as finance_mod

    def _run_with_vix(vix_val):
        # Must clear cache each call so a fresh yfinance call is made
        finance_mod._MACRO_CACHE.clear()
        with patch("yfinance.Ticker") as mock_cls:

            def make_ticker(sym):
                mock = MagicMock()
                mock.history.return_value = _make_price_history([100.0, vix_val])
                return mock

            mock_cls.side_effect = make_ticker
            return finance_tools["get_macro_context"]()

    assert "Risk-On" in _run_with_vix(12.0)["market_regime"]
    assert _run_with_vix(17.0)["market_regime"] == "Normal"
    assert "Caution" in _run_with_vix(25.0)["market_regime"]
    assert "Risk-Off" in _run_with_vix(35.0)["market_regime"]


def test_get_macro_context_caches_result(finance_tools):
    """Result should be returned from cache on second call."""
    import server.finance as finance_mod

    finance_mod._MACRO_CACHE.clear()

    call_count = 0

    def make_ticker(sym):
        nonlocal call_count
        call_count += 1
        mock = MagicMock()
        mock.history.return_value = _make_price_history([100.0, 100.0])
        return mock

    with patch("yfinance.Ticker", side_effect=make_ticker):
        finance_tools["get_macro_context"]()
        first_call_count = call_count

    # Second call should hit cache — no new Ticker instances
    with patch("yfinance.Ticker", side_effect=make_ticker):
        finance_tools["get_macro_context"]()

    assert call_count == first_call_count  # no additional calls


def test_get_macro_context_handles_error(finance_tools):
    """Test that failures return an error dict, not an exception."""
    with patch("yfinance.Ticker", side_effect=Exception("network error")):
        result = finance_tools["get_macro_context"]()

    assert "error" in result
    assert result["error_type"] == "unknown"
