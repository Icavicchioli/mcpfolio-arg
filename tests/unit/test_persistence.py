"""Unit tests for ThesisStore (src/persistence.py)."""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from persistence import ThesisStore

_PASSWORD = "test-password-123"
_WRONG_PASSWORD = "wrong-password"


def _make_analysis(
    ticker: str = "AAPL",
    recommendation: str = "BUY",
    confidence: float = 0.85,
    key_risk: str = "High valuation",
    fair_value: float = 210.0,
    risk_score: float = 45.0,
    price: float = 195.50,
    ai_analysis: str = "Strong fundamentals.",
    timestamp: datetime | None = None,
) -> MagicMock:
    """Build a minimal AnalysisResponse mock."""
    analysis = MagicMock()
    analysis.ticker = ticker
    analysis.timestamp = timestamp or datetime.now()
    analysis.recommendation = recommendation
    analysis.confidence = confidence
    analysis.key_risk = key_risk
    analysis.fair_value = fair_value
    analysis.risk_score = risk_score
    analysis.market_snapshot = {"current_price": price}
    analysis.ai_analysis = ai_analysis
    return analysis


# ---------------------------------------------------------------------------
# Lock / unlock
# ---------------------------------------------------------------------------


def test_thesis_store_locked_by_default(tmp_path):
    store = ThesisStore(tmp_path)
    assert not store.is_unlocked()


def test_unlock_correct_password(tmp_path):
    store = ThesisStore(tmp_path)
    result = store.unlock(_PASSWORD)
    assert result is True
    assert store.is_unlocked()


def test_unlock_wrong_password_stays_locked(tmp_path):
    store = ThesisStore(tmp_path)
    # Create a real encrypted file first
    store.unlock(_PASSWORD)
    store.save(_make_analysis())
    store.lock()

    # Now try wrong password
    result = store.unlock(_WRONG_PASSWORD)
    assert result is False
    assert not store.is_unlocked()


# ---------------------------------------------------------------------------
# Save / load
# ---------------------------------------------------------------------------


def test_save_raises_401_when_locked(tmp_path):
    from fastapi import HTTPException

    store = ThesisStore(tmp_path)
    with pytest.raises(HTTPException) as exc_info:
        store.save(_make_analysis())
    assert exc_info.value.status_code == 401


def test_save_persists_record(tmp_path):
    store = ThesisStore(tmp_path)
    store.unlock(_PASSWORD)

    store.save(_make_analysis(ticker="AAPL", recommendation="BUY", confidence=0.85))

    records = store.load_all()
    assert len(records) == 1
    assert records[0]["ticker"] == "AAPL"
    assert records[0]["recommendation"] == "BUY"
    assert records[0]["confidence"] == 0.85


def test_load_all_returns_newest_first(tmp_path):
    store = ThesisStore(tmp_path)
    store.unlock(_PASSWORD)

    t1 = datetime(2025, 1, 1, 12, 0, 0)
    t2 = datetime(2025, 1, 2, 12, 0, 0)

    store.save(_make_analysis(ticker="AAPL", timestamp=t1))
    store.save(_make_analysis(ticker="MSFT", timestamp=t2))

    records = store.load_all()
    assert len(records) == 2
    assert records[0]["timestamp"] > records[1]["timestamp"]  # newest first


def test_multiple_saves_accumulate(tmp_path):
    store = ThesisStore(tmp_path)
    store.unlock(_PASSWORD)

    store.save(_make_analysis(ticker="AAPL"))
    store.save(_make_analysis(ticker="AAPL"))
    store.save(_make_analysis(ticker="MSFT"))

    assert len(store.load_all()) == 3


def test_empty_state_returns_empty_list(tmp_path):
    store = ThesisStore(tmp_path)
    store.unlock(_PASSWORD)
    # No thesis.enc file yet
    assert store.load_all() == []


# ---------------------------------------------------------------------------
# Filtered queries
# ---------------------------------------------------------------------------


def test_get_history_filters_to_ticker(tmp_path):
    store = ThesisStore(tmp_path)
    store.unlock(_PASSWORD)

    store.save(_make_analysis(ticker="AAPL"))
    store.save(_make_analysis(ticker="MSFT"))
    store.save(_make_analysis(ticker="AAPL"))

    aapl = store.get_history("AAPL")
    assert len(aapl) == 2
    assert all(r["ticker"] == "AAPL" for r in aapl)


def test_get_history_respects_limit(tmp_path):
    store = ThesisStore(tmp_path)
    store.unlock(_PASSWORD)

    for _ in range(5):
        store.save(_make_analysis(ticker="AAPL"))

    assert len(store.get_history("AAPL", limit=2)) == 2


def test_get_latest_returns_most_recent(tmp_path):
    store = ThesisStore(tmp_path)
    store.unlock(_PASSWORD)

    t1 = datetime(2025, 1, 1, 10, 0, 0)
    t2 = datetime(2025, 1, 2, 10, 0, 0)

    store.save(_make_analysis(ticker="AAPL", recommendation="HOLD", timestamp=t1))
    store.save(_make_analysis(ticker="AAPL", recommendation="BUY", timestamp=t2))

    latest = store.get_latest("AAPL")
    assert latest is not None
    assert latest["recommendation"] == "BUY"


def test_get_latest_unknown_ticker_returns_none(tmp_path):
    store = ThesisStore(tmp_path)
    store.unlock(_PASSWORD)

    store.save(_make_analysis(ticker="AAPL"))

    assert store.get_latest("ZZZZ") is None


def test_get_recent_returns_across_tickers_newest_first(tmp_path):
    store = ThesisStore(tmp_path)
    store.unlock(_PASSWORD)

    t1 = datetime(2025, 1, 1, 9, 0, 0)
    t2 = datetime(2025, 1, 3, 9, 0, 0)
    t3 = datetime(2025, 1, 2, 9, 0, 0)

    store.save(_make_analysis(ticker="AAPL", timestamp=t1))
    store.save(_make_analysis(ticker="MSFT", timestamp=t2))
    store.save(_make_analysis(ticker="GOOG", timestamp=t3))

    recent = store.get_recent(10)
    assert len(recent) == 3
    # Newest first
    assert recent[0]["ticker"] == "MSFT"
    assert recent[1]["ticker"] == "GOOG"
    assert recent[2]["ticker"] == "AAPL"
