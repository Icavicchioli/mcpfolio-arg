"""Indicative ARS/USD CCL quotes from DolarAPI."""

from __future__ import annotations

import math
import time
from datetime import datetime
from typing import Any

import httpx

from src.market.cedears import quote_freshness

CCL_URL = "https://dolarapi.com/v1/dolares/contadoconliqui"
CCL_SOURCE = "DolarAPI (Contado con liquidacion)"
CCL_CACHE_SECONDS = 300

_cached_quote: dict[str, Any] | None = None
_cached_at = 0.0


def parse_ccl_payload(payload: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Validate a DolarAPI response and calculate its buy/sell midpoint."""
    try:
        buy = float(payload["compra"])
        sell = float(payload["venta"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("CCL response is missing numeric compra/venta") from error

    if not all(math.isfinite(value) and value > 0 for value in (buy, sell)):
        raise ValueError("CCL response contains a non-positive or invalid quote")

    quote_as_of = payload.get("fechaActualizacion")
    return {
        "ars_per_usd": (buy + sell) / 2,
        "buy": buy,
        "sell": sell,
        "quote_as_of": quote_as_of,
        "quote_status": quote_freshness(quote_as_of, now=now, max_age_days=1),
        "source": CCL_SOURCE,
        "market": payload.get("casa", "contadoconliqui"),
    }


async def get_ccl_quote(*, force_refresh: bool = False) -> dict[str, Any]:
    """Fetch and briefly cache a dated CCL quote; never silently substitute FX."""
    global _cached_quote, _cached_at
    now = time.monotonic()
    if not force_refresh and _cached_quote and now - _cached_at < CCL_CACHE_SECONDS:
        return dict(_cached_quote)

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(CCL_URL)
        response.raise_for_status()
        quote = parse_ccl_payload(response.json())

    _cached_quote = quote
    _cached_at = time.monotonic()
    return dict(quote)


def clear_ccl_cache() -> None:
    """Clear the process-local CCL cache for deterministic tests."""
    global _cached_quote, _cached_at
    _cached_quote = None
    _cached_at = 0.0