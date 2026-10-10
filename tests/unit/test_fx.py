"""Tests for dated CCL quotes."""

from datetime import datetime, timezone
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.market.fx import parse_ccl_payload


def test_parse_ccl_payload_uses_midpoint_and_keeps_provenance():
    quote = parse_ccl_payload(
        {
            "compra": 1605.5,
            "venta": 1606.6,
            "fechaActualizacion": "2026-10-10T20:57:00.000Z",
            "casa": "contadoconliqui",
        },
        now=datetime(2026, 10, 10, 21, 0, tzinfo=timezone.utc),
    )

    assert quote["ars_per_usd"] == 1606.05
    assert quote["quote_status"] == "fresh"
    assert quote["quote_as_of"] == "2026-10-10T20:57:00.000Z"
    assert quote["source"] == "DolarAPI (Contado con liquidacion)"


def test_parse_ccl_payload_marks_old_or_missing_timestamps():
    stale = parse_ccl_payload(
        {"compra": 1000, "venta": 1002, "fechaActualizacion": "2026-10-08T20:00:00Z"},
        now=datetime(2026, 10, 10, 21, 0, tzinfo=timezone.utc),
    )
    unknown = parse_ccl_payload(
        {"compra": 1000, "venta": 1002},
        now=datetime(2026, 10, 10, 21, 0, tzinfo=timezone.utc),
    )

    assert stale["quote_status"] == "stale"
    assert unknown["quote_status"] == "unknown"


@pytest.mark.parametrize(
    "payload",
    [
        {"compra": 0, "venta": 10},
        {"compra": "bad", "venta": 10},
        {"venta": 10},
    ],
)
def test_parse_ccl_payload_rejects_invalid_quotes(payload):
    with pytest.raises(ValueError):
        parse_ccl_payload(payload)


def test_portfolio_price_endpoint_uses_ccl_for_cross_currency_pnl(monkeypatch):
    from src.market import fx
    from src.tools import lazy_loader
    from src.web import main as web_main

    class MarketTool:
        name = "get_market_snapshot"

        async def ainvoke(self, request):
            return {
                "ticker": request["ticker"],
                "current_price": 20970.0,
                "currency": "ARS",
                "quote_as_of": "2026-10-09T19:59:53-03:00",
                "quote_status": "fresh",
            }

    ccl = {
        "ars_per_usd": 1606.05,
        "quote_as_of": "2026-10-10T20:57:00Z",
        "quote_status": "fresh",
        "source": "DolarAPI CCL",
    }
    monkeypatch.setattr(lazy_loader, "get_mcp_tools", AsyncMock(return_value=[MarketTool()]))
    monkeypatch.setattr(fx, "get_ccl_quote", AsyncMock(return_value=ccl))
    request = {
        "positions": [
            {
                "ticker": "SPY.BA",
                "quantity": 66,
                "cost_basis": 11.75,
                "cost_currency": "USD",
                "asset_type": "cedear",
                "underlying_ticker": "SPY",
            }
        ]
    }

    result = asyncio.run(web_main.get_portfolio_prices(request))
    metrics = result["quotes"]["SPY.BA"]["position_metrics"]

    assert result["prices"]["SPY.BA"] == 20970.0
    assert result["fx"] == ccl
    assert metrics["market_value"] == 1_384_020
    assert metrics["market_value_currency"] == "ARS"
    assert metrics["pnl_currency"] == "USD"
    assert metrics["valuation_status"] == "comparable_via_ccl"
    assert metrics["fx_quote"]["source"] == "DolarAPI CCL"
    assert result["totals"]["pnl_by_currency"]["USD"] == pytest.approx(
        1_384_020 / 1606.05 - 66 * 11.75
    )