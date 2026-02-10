from datetime import datetime

import pytest

from src.web.main import PortfolioItem, SecurePortfolioManager


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


def test_portfolio_wipe(tmp_path):
    pm = SecurePortfolioManager(tmp_path)
    pm.unlock("pass")
    pm.save([PortfolioItem(ticker="TSLA", quantity=1, cost_basis=200.0, added_at=datetime.now())])

    assert (tmp_path / "portfolio.enc").exists()
    pm.wipe()
    assert not (tmp_path / "portfolio.enc").exists()
    assert not (tmp_path / "portfolio.salt").exists()
    assert pm.is_unlocked() is False
