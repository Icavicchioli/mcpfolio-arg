from src.server.finance import _get_trend_data_logic


def test_get_trend_data_valid():
    result = _get_trend_data_logic("AAPL", period="5d")
    assert "ticker" in result
    assert result["ticker"] == "AAPL"
    assert "points" in result
    assert len(result["points"]) > 0
    assert "date" in result["points"][0]
    assert "price" in result["points"][0]


def test_get_trend_data_invalid():
    result = _get_trend_data_logic("INVALID_TICKER_12345")
    assert "error" in result
    assert result["error_type"] == "no_data"
