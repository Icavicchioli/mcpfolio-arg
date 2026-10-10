"""Tests for CEDEAR conversions and currency-safe portfolio valuations."""

from datetime import date, datetime, timezone

from src.market.cedears import (
    aggregate_position_metrics,
    calculate_position_metrics,
    cedear_ratio_status,
    quote_freshness,
)


def test_cedear_exposure_uses_cedears_per_underlying_ratio():
    result = calculate_position_metrics(
        quantity=25,
        cost_basis=27000,
        cost_currency="ARS",
        quote={"current_price": 27200, "currency": "ARS", "quote_as_of": "2026-10-09T00:00:00-03:00"},
        asset_type="cedear",
        underlying_ticker="aapl",
        cedears_per_underlying=10,
        ratio_as_of=date(2026, 10, 1),
    )

    assert result["underlying_ticker"] == "AAPL"
    assert result["underlying_equivalent_quantity"] == 2.5
    assert result["ratio_status"] == "user_provided_unverified"
    assert result["ratio_verified"] is False
    assert result["market_value"] == 680000
    assert result["market_value_currency"] == "ARS"
    assert result["pnl"] == 5000
    assert result["pnl_percent"] == (5000 / 675000) * 100


def test_missing_or_stale_ratio_is_reported_without_inventing_exposure():
    missing = calculate_position_metrics(
        quantity=4,
        cost_basis=100,
        cost_currency="ARS",
        quote={"current_price": 110, "currency": "ARS"},
        asset_type="cedear",
        underlying_ticker="MSFT",
    )
    stale = cedear_ratio_status(10, date(2024, 1, 1), now=date(2026, 10, 1))

    assert missing["underlying_equivalent_quantity"] is None
    assert missing["ratio_status"] == "missing"
    assert stale == "stale_unverified"


def test_currency_mismatch_does_not_calculate_pnl_or_convert_value():
    result = calculate_position_metrics(
        quantity=10,
        cost_basis=100,
        cost_currency="ARS",
        quote={"current_price": 12, "currency": "USD"},
    )

    assert result["market_value"] == 120
    assert result["market_value_currency"] == "USD"
    assert result["pnl"] is None
    assert result["pnl_percent"] is None
    assert result["valuation_status"] == "currency_mismatch"


def test_portfolio_totals_are_grouped_by_currency():
    ars = calculate_position_metrics(
        quantity=10,
        cost_basis=100,
        cost_currency="ARS",
        quote={"current_price": 120, "currency": "ARS"},
    )
    usd = calculate_position_metrics(
        quantity=2,
        cost_basis=50,
        cost_currency="USD",
        quote={"current_price": 60, "currency": "USD"},
    )
    mismatched = calculate_position_metrics(
        quantity=3,
        cost_basis=500,
        cost_currency="ARS",
        quote={"current_price": 2, "currency": "USD"},
    )
    totals = aggregate_position_metrics([ars, usd, mismatched])

    assert totals["market_value_by_currency"] == {"ARS": 1200.0, "USD": 126.0}
    assert totals["cost_by_currency"] == {"ARS": 2500.0, "USD": 100.0}
    assert totals["pnl_by_currency"] == {"ARS": 200.0, "USD": 20.0}
    assert totals["not_comparable_positions"] == 1


def test_quote_freshness_does_not_assume_missing_timestamp_is_current():
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)

    assert quote_freshness(None, now=now) == "unknown"
    assert quote_freshness("2026-10-09T00:00:00Z", now=now) == "fresh"
    assert quote_freshness("2026-09-01T00:00:00Z", now=now) == "stale"