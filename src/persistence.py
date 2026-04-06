# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Adam Karp
"""
Encrypted thesis history persistence.

Uses the same Fernet key derivation as SecurePortfolioManager — same salt file,
same password — so unlocking the portfolio also unlocks thesis history.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from fastapi import HTTPException

if TYPE_CHECKING:
    from src.web.main import AnalysisResponse


class ThesisRecord(TypedDict):
    ticker: str
    timestamp: str  # ISO 8601
    recommendation: str | None
    confidence: float | None
    key_risk: str | None
    fair_value: float | None
    risk_score: float
    price: float | None
    ai_analysis: str


class ThesisStore:
    """
    Encrypted thesis history — same Fernet key as the portfolio.

    The key is derived from the user's password + the shared salt in data/.
    thesis.enc doesn't exist until the first save; read returns [] gracefully
    when the file is absent.
    """

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.thesis_path = data_dir / "thesis.enc"
        self.salt_path = data_dir / "portfolio.salt"
        self.fernet: Fernet | None = None

    # ------------------------------------------------------------------
    # Salt helpers (shared with SecurePortfolioManager)
    # ------------------------------------------------------------------

    def _get_or_create_salt(self) -> bytes:
        if self.salt_path.exists():
            return self.salt_path.read_bytes()
        salt = os.urandom(16)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.salt_path.write_bytes(salt)
        return salt

    # ------------------------------------------------------------------
    # Lock / unlock
    # ------------------------------------------------------------------

    def unlock(self, password: str) -> bool:
        """Derive Fernet key from password + shared salt. Return True on success."""
        try:
            salt = self._get_or_create_salt()
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=390000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
            fernet = Fernet(key)

            # If data exists, verify the key is correct by attempting a decrypt
            if self.thesis_path.exists():
                encrypted = self.thesis_path.read_bytes()
                fernet.decrypt(encrypted)  # raises InvalidToken if key is wrong

            self.fernet = fernet
            return True
        except InvalidToken:
            self.fernet = None
            return False
        except Exception:
            self.fernet = None
            return False

    def lock(self) -> None:
        """Clear the key from memory."""
        self.fernet = None

    def is_unlocked(self) -> bool:
        return self.fernet is not None

    # ------------------------------------------------------------------
    # Read / write
    # ------------------------------------------------------------------

    def _require_unlocked(self) -> None:
        if not self.fernet:
            raise HTTPException(status_code=401, detail="Portfolio locked")

    def _load_raw(self) -> list[ThesisRecord]:
        """Decrypt and return all records; returns [] if file absent."""
        if not self.thesis_path.exists():
            return []
        encrypted = self.thesis_path.read_bytes()
        if self.fernet is None:
            raise RuntimeError("ThesisStore is locked")
        decrypted = self.fernet.decrypt(encrypted)
        return list(json.loads(decrypted))

    def _save_raw(self, records: list[ThesisRecord]) -> None:
        raw = json.dumps(records).encode()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.fernet is None:
            raise RuntimeError("ThesisStore is locked")
        self.thesis_path.write_bytes(self.fernet.encrypt(raw))

    def save(self, analysis: AnalysisResponse) -> None:
        """Append one ThesisRecord derived from an AnalysisResponse."""
        self._require_unlocked()
        record: ThesisRecord = {
            "ticker": analysis.ticker,
            "timestamp": analysis.timestamp.isoformat(),
            "recommendation": analysis.recommendation,
            "confidence": analysis.confidence,
            "key_risk": analysis.key_risk,
            "fair_value": analysis.fair_value,
            "risk_score": analysis.risk_score,
            "price": analysis.market_snapshot.get("current_price"),
            "ai_analysis": analysis.ai_analysis,
        }
        records = self._load_raw()
        records.append(record)
        self._save_raw(records)

    def load_all(self) -> list[ThesisRecord]:
        """Return all records sorted newest-first."""
        self._require_unlocked()
        records = self._load_raw()
        return sorted(records, key=lambda r: r["timestamp"], reverse=True)

    def get_history(self, ticker: str, limit: int = 20) -> list[ThesisRecord]:
        """Return up to `limit` records for a single ticker, newest-first."""
        self._require_unlocked()
        ticker = ticker.upper()
        records = [r for r in self._load_raw() if r["ticker"] == ticker]
        records.sort(key=lambda r: r["timestamp"], reverse=True)
        return records[:limit]

    def get_latest(self, ticker: str) -> ThesisRecord | None:
        """Return the most recent record for a ticker, or None if none exist."""
        history = self.get_history(ticker, limit=1)
        return history[0] if history else None

    def get_recent(self, limit: int = 50) -> list[ThesisRecord]:
        """Return the most recent `limit` records across all tickers, newest-first."""
        self._require_unlocked()
        records = self._load_raw()
        records.sort(key=lambda r: r["timestamp"], reverse=True)
        return records[:limit]
