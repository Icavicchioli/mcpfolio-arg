import asyncio
from datetime import datetime

import pytest

from fastapi import HTTPException

from src.web import main as web_main
from src.web.main import (
    AddPortfolioUnitsRequest,
    PortfolioImportRequest,
    PortfolioItem,
    SecurePortfolioManager,
)


def test_portfolio_manager_lifecycle(tmp_path):
    pm = SecurePortfolioManager(tmp_path)
    password = "secure-test-password"

    # 1. Unlock with new password
    assert pm.unlock(password) is True
    assert pm.is_unlocked() is True

    # 2. Save and Load
    item = PortfolioItem(ticker="AAPL", quantity=10, cost_basis=150.0, added_at=datetime.now())
    pm.save([item])

    loaded = pm.load()
    assert len(loaded) == 1
    assert loaded[0].ticker == "AAPL"

    # 3. Lock and verify access denied
    pm.lock()
    assert pm.is_unlocked() is False
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        pm.load()

    # 4. Re-unlock with same password
    assert pm.unlock(password) is True
    loaded = pm.load()
    assert len(loaded) == 1

    # 5. Re-unlock with wrong password
    pm.lock()
    assert pm.unlock("wrong-password") is False
    assert pm.is_unlocked() is False


def test_legacy_holding_defaults_to_usd_equity():
    item = PortfolioItem(
        ticker="AAPL",
        quantity=10,
        cost_basis=150.0,
        added_at=datetime.now(),
    )

    assert item.asset_type == "equity"
    assert item.cost_currency == "USD"
    assert item.underlying_ticker is None
    assert item.cedears_per_underlying is None


def test_portfolio_wipe(tmp_path):
    pm = SecurePortfolioManager(tmp_path)
    pm.unlock("pass")
    pm.save([PortfolioItem(ticker="TSLA", quantity=1, cost_basis=200.0, added_at=datetime.now())])

    assert (tmp_path / "portfolio.enc").exists()
    pm.wipe()
    assert not (tmp_path / "portfolio.enc").exists()
    assert not (tmp_path / "portfolio.salt").exists()
    assert pm.is_unlocked() is False


def test_portfolio_import_merges_and_updates_in_one_encrypted_store(tmp_path, monkeypatch):
    manager = SecurePortfolioManager(tmp_path)
    assert manager.unlock("temporary-test-password")
    manager.save(
        [
            PortfolioItem(
                ticker="SPY.BA",
                quantity=66,
                cost_basis=11.75,
                added_at=datetime(2026, 1, 1),
                asset_type="cedear",
                cost_currency="USD",
            )
        ]
    )
    monkeypatch.setattr(web_main.session, "portfolio_manager", manager)
    request = PortfolioImportRequest(
        holdings=[
            PortfolioItem(
                ticker="spy.ba",
                quantity=72,
                cost_basis=11.8,
                added_at=datetime(2026, 1, 1),
                asset_type="cedear",
                cost_currency="USD",
            ),
            PortfolioItem(
                ticker="EEM.BA",
                quantity=38,
                cost_basis=13.22,
                added_at=datetime(2026, 1, 2),
                asset_type="cedear",
                cost_currency="USD",
            ),
        ]
    )

    result = asyncio.run(web_main.import_portfolio(request))
    holdings = {item.ticker: item for item in manager.load()}

    assert result == {"status": "imported", "added": 1, "updated": 1}
    assert set(holdings) == {"SPY.BA", "EEM.BA"}
    assert holdings["SPY.BA"].quantity == 72
    assert holdings["SPY.BA"].cost_basis == 11.8


def test_portfolio_import_rejects_duplicates_without_writing(tmp_path, monkeypatch):
    manager = SecurePortfolioManager(tmp_path)
    assert manager.unlock("temporary-test-password")
    item = PortfolioItem(ticker="SPY.BA", quantity=66, cost_basis=11.75, added_at=datetime.now())
    manager.save([item])
    encrypted_before = (tmp_path / "portfolio.enc").read_bytes()
    monkeypatch.setattr(web_main.session, "portfolio_manager", manager)
    duplicate_request = PortfolioImportRequest(
        holdings=[item, item.model_copy(update={"ticker": "spy.ba", "quantity": 1})]
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(web_main.import_portfolio(duplicate_request))

    assert error.value.status_code == 422
    assert (tmp_path / "portfolio.enc").read_bytes() == encrypted_before


def test_portfolio_import_requires_unlock(tmp_path, monkeypatch):
    manager = SecurePortfolioManager(tmp_path)
    monkeypatch.setattr(web_main.session, "portfolio_manager", manager)
    request = PortfolioImportRequest(
        holdings=[
            PortfolioItem(ticker="SPY.BA", quantity=66, cost_basis=11.75, added_at=datetime.now())
        ]
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(web_main.import_portfolio(request))

    assert error.value.status_code == 401


def test_add_units_updates_quantity_and_weighted_average_in_same_currency(tmp_path, monkeypatch):
    manager = SecurePortfolioManager(tmp_path)
    assert manager.unlock("temporary-test-password")
    original = PortfolioItem(
        ticker="SPY.BA",
        quantity=66,
        cost_basis=11.75,
        added_at=datetime(2026, 1, 1),
        asset_type="cedear",
        cost_currency="USD",
    )
    manager.save([original])
    monkeypatch.setattr(web_main.session, "portfolio_manager", manager)

    result = asyncio.run(
        web_main.add_units_to_portfolio_item(
            "spy.ba",
            AddPortfolioUnitsRequest(quantity=34, cost_basis=12.5, cost_currency="USD"),
        )
    )
    holding = manager.load()[0]

    assert result["status"] == "updated"
    assert holding.quantity == 100
    assert holding.cost_basis == pytest.approx((66 * 11.75 + 34 * 12.5) / 100)
    assert holding.added_at == datetime(2026, 1, 1)


def test_add_units_rejects_currency_mismatch_without_saving(tmp_path, monkeypatch):
    manager = SecurePortfolioManager(tmp_path)
    assert manager.unlock("temporary-test-password")
    manager.save(
        [
            PortfolioItem(
                ticker="SPY.BA",
                quantity=66,
                cost_basis=11.75,
                added_at=datetime.now(),
                asset_type="cedear",
                cost_currency="USD",
            )
        ]
    )
    encrypted_before = (tmp_path / "portfolio.enc").read_bytes()
    monkeypatch.setattr(web_main.session, "portfolio_manager", manager)

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            web_main.add_units_to_portfolio_item(
                "SPY.BA",
                AddPortfolioUnitsRequest(quantity=1, cost_basis=20000, cost_currency="ARS"),
            )
        )

    assert error.value.status_code == 422
    assert (tmp_path / "portfolio.enc").read_bytes() == encrypted_before
