"""Unit tests for shared prompt formatters."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from prompts import format_comparison_context, format_single_context

SNAPSHOT = {
    "current_price": 195.50,
    "market_cap": 3_000_000_000_000,
    "pe_ratio": 28.5,
    "dividend_yield": 0.0055,
    "volatility_52_week_pct": 35.2,
    "high_52_week": 220.0,
    "low_52_week": 160.0,
    "change_percent": 1.23,
    "eps": 6.08,
    "revenue": 380_000_000_000,
}

SENTIMENT_AGGREGATE = [
    {"period": "2025Q1", "strongBuy": 20, "buy": 15, "hold": 8, "sell": 2, "strongSell": 0},
    {"period": "2025Q2", "strongBuy": 18, "buy": 14, "hold": 9, "sell": 2, "strongSell": 1},
]

SENTIMENT_FIRM = [
    {"firm": "Goldman Sachs", "grade": "Buy", "action": "maintain"},
    {"firm": "JP Morgan", "grade": "Overweight", "action": "upgrade"},
]

NEWS = [
    {"title": "AAPL hits record high", "publisher": "Reuters", "link": "http://example.com"},
    {"title": "Apple launches new product", "source": "Bloomberg"},
]


def test_format_single_context_basic():
    ctx = format_single_context("AAPL", SNAPSHOT, None, None)
    assert "AAPL" in ctx
    assert "$195.5" in ctx
    assert "No data available" in ctx  # no sentiment, no news


def test_format_single_context_with_aggregate_sentiment():
    ctx = format_single_context("AAPL", SNAPSHOT, SENTIMENT_AGGREGATE, None)
    assert "ANALYST CONSENSUS" in ctx
    assert "Strong Buy" in ctx
    assert "38" in ctx  # total strongBuy across two periods


def test_format_single_context_with_firm_sentiment():
    ctx = format_single_context("AAPL", SNAPSHOT, SENTIMENT_FIRM, None)
    assert "Goldman Sachs" in ctx
    assert "Overweight" in ctx


def test_format_single_context_with_news():
    ctx = format_single_context("AAPL", SNAPSHOT, None, NEWS)
    assert "AAPL hits record high" in ctx
    assert "Reuters" in ctx


def test_format_single_context_market_cap_billions():
    ctx = format_single_context("AAPL", SNAPSHOT, None, None)
    assert "$3000.0B" in ctx


def test_format_single_context_dividend():
    ctx = format_single_context("AAPL", SNAPSHOT, None, None)
    assert "0.55%" in ctx


def test_format_single_context_no_dividend():
    snap = {**SNAPSHOT, "dividend_yield": None}
    ctx = format_single_context("AAPL", snap, None, None)
    assert "None" in ctx


def test_format_single_context_missing_price():
    snap = {**SNAPSHOT, "current_price": None}
    ctx = format_single_context("AAPL", snap, None, None)
    assert "AAPL" in ctx  # should not crash


def test_format_comparison_context_produces_both_blocks():
    snap_b = {**SNAPSHOT, "current_price": 420.0, "market_cap": 2_500_000_000_000}
    ctx = format_comparison_context("AAPL", SNAPSHOT, None, None, "MSFT", snap_b, None, None)
    assert "AAPL" in ctx
    assert "MSFT" in ctx
    # separator between the two blocks
    assert "=" * 10 in ctx


def test_format_comparison_context_with_data():
    snap_b = {**SNAPSHOT, "current_price": 420.0}
    ctx = format_comparison_context(
        "AAPL",
        SNAPSHOT,
        SENTIMENT_AGGREGATE,
        NEWS,
        "MSFT",
        snap_b,
        SENTIMENT_FIRM,
        None,
    )
    assert "ANALYST CONSENSUS" in ctx  # from AAPL block (aggregate)
    assert "Goldman Sachs" in ctx  # from MSFT block (firm)
