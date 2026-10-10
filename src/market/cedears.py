"""CEDEAR metadata and currency-safe position calculations.

Ratios are supplied per holding because the market quote provider does not
publish an authoritative, versioned CEDEAR conversion table.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

DEFAULT_QUOTE_MAX_AGE_DAYS = 7
DEFAULT_RATIO_MAX_AGE_DAYS = 365


def normalize_currency(value: Any) -> str | None:
    """Return a normalized ISO-like currency code, or None if unavailable."""
    if not isinstance(value, str):
        return None
    currency = value.strip().upper()
    return currency if len(currency) == 3 and currency.isalpha() else None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def quote_freshness(
    quote_as_of: Any,
    *,
    now: datetime | None = None,
    max_age_days: int = DEFAULT_QUOTE_MAX_AGE_DAYS,
) -> str:
    """Classify quote age without treating a missing timestamp as current."""
    timestamp = _parse_datetime(quote_as_of)
    if timestamp is None:
        return "unknown"
    current = _parse_datetime(now or datetime.now(timezone.utc))
    if current is None:
        return "unknown"
    age = current - timestamp
    if age < timedelta(days=-1):
        return "unknown"
    return "stale" if age > timedelta(days=max_age_days) else "fresh"


def cedear_ratio_status(
    cedears_per_underlying: float | None,
    ratio_as_of: date | datetime | str | None = None,
    *,
    now: date | None = None,
    max_age_days: int = DEFAULT_RATIO_MAX_AGE_DAYS,
) -> str:
    """Ratios remain unverified even when provenance and date are provided."""
    if cedears_per_underlying is None:
        return "missing"
    try:
        ratio = float(cedears_per_underlying)
    except (TypeError, ValueError):
        return "invalid"
    if not math.isfinite(ratio) or ratio <= 0:
        return "invalid"

    ratio_date = _parse_datetime(ratio_as_of)
    if ratio_date is not None:
        current = _parse_datetime(now or datetime.now(timezone.utc))
        if current is not None and current - ratio_date > timedelta(days=max_age_days):
            return "stale_unverified"
    return "user_provided_unverified"


def calculate_position_metrics(
    *,
    quantity: float,
    cost_basis: float,
    cost_currency: str | None,
    quote: dict[str, Any],
    asset_type: str = "equity",
    underlying_ticker: str | None = None,
    cedears_per_underlying: float | None = None,
    ratio_as_of: date | datetime | str | None = None,
) -> dict[str, Any]:
    """Calculate values only in comparable units/currencies; never infer FX."""
    quote_currency = normalize_currency(quote.get("currency"))
    normalized_cost_currency = normalize_currency(cost_currency)
    price = quote.get("current_price")
    valid_price = isinstance(price, int | float) and not isinstance(price, bool)
    valid_price = valid_price and math.isfinite(float(price)) and float(price) > 0

    market_value = float(quantity) * float(price) if valid_price else None
    cost_value = float(quantity) * float(cost_basis)
    currency_matches = (
        quote_currency is not None
        and normalized_cost_currency is not None
        and quote_currency == normalized_cost_currency
    )
    comparable = bool(valid_price and currency_matches)

    metrics: dict[str, Any] = {
        "market_value": market_value,
        "market_value_currency": quote_currency,
        "cost_value": cost_value,
        "cost_currency": normalized_cost_currency,
        "pnl": market_value - cost_value if comparable else None,
        "pnl_percent": (
            (market_value - cost_value) / cost_value * 100
            if comparable and cost_value > 0
            else None
        ),
        "valuation_status": (
            "comparable"
            if comparable
            else "missing_price"
            if not valid_price
            else "currency_unknown"
            if quote_currency is None or normalized_cost_currency is None
            else "currency_mismatch"
        ),
        "quote_currency": quote_currency,
        "quote_as_of": quote.get("quote_as_of"),
        "quote_status": quote.get("quote_status", "unknown"),
    }

    if asset_type == "cedear":
        ratio_status = cedear_ratio_status(cedears_per_underlying, ratio_as_of)
        ratio = float(cedears_per_underlying) if ratio_status in {
            "user_provided_unverified",
            "stale_unverified",
        } else None
        metrics.update(
            {
                "underlying_ticker": underlying_ticker.upper() if underlying_ticker else None,
                "cedears_per_underlying": ratio,
                "underlying_equivalent_quantity": (
                    float(quantity) / ratio if ratio and underlying_ticker else None
                ),
                "ratio_status": ratio_status,
                "ratio_as_of": ratio_as_of.isoformat() if isinstance(ratio_as_of, (date, datetime)) else ratio_as_of,
                "ratio_verified": False,
            }
        )
    return metrics


def aggregate_position_metrics(positions: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate comparable amounts separately for each currency."""
    market_value_by_currency: dict[str, float] = {}
    cost_by_currency: dict[str, float] = {}
    pnl_by_currency: dict[str, float] = {}
    pnl_cost_by_currency: dict[str, float] = {}
    not_comparable = 0

    for position in positions:
        market_currency = position.get("market_value_currency")
        market_value = position.get("market_value")
        if market_currency and isinstance(market_value, int | float):
            market_value_by_currency[market_currency] = (
                market_value_by_currency.get(market_currency, 0.0) + float(market_value)
            )

        cost_currency = position.get("cost_currency")
        cost_value = position.get("cost_value")
        if cost_currency and isinstance(cost_value, int | float):
            cost_by_currency[cost_currency] = cost_by_currency.get(cost_currency, 0.0) + float(
                cost_value
            )

        pnl = position.get("pnl")
        if position.get("valuation_status") == "comparable" and market_currency:
            pnl_by_currency[market_currency] = pnl_by_currency.get(market_currency, 0.0) + float(
                pnl
            )
            pnl_cost_by_currency[market_currency] = (
                pnl_cost_by_currency.get(market_currency, 0.0) + float(cost_value)
            )
        else:
            not_comparable += 1

    return {
        "market_value_by_currency": market_value_by_currency,
        "cost_by_currency": cost_by_currency,
        "pnl_by_currency": pnl_by_currency,
        "pnl_percent_by_currency": {
            currency: pnl / pnl_cost_by_currency[currency] * 100
            for currency, pnl in pnl_by_currency.items()
            if pnl_cost_by_currency.get(currency, 0) > 0
        },
        "not_comparable_positions": not_comparable,
    }