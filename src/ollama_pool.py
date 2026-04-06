# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Adam Karp
"""
Ollama connection pooling for better performance.

Maintains a pool of reusable Ollama client connections
to avoid connection overhead on each request.
"""

import asyncio

import ollama

from src.config import get_settings
from src.logging_config import get_logger

logger = get_logger(__name__)


class OllamaPool:
    """Connection pool for Ollama with keep-alive"""

    def __init__(self, pool_size: int = 3):
        self.pool_size = pool_size
        self.pool: list[ollama.Client] = []
        self._lock = asyncio.Lock()
        settings = get_settings()
        self.host = settings.ollama_host
        logger.info("ollama_pool_initialized", pool_size=pool_size, host=self.host)

    def get_client(self) -> ollama.Client:
        """Get a client from pool (or create new)

        Returns:
            ollama.Client instance
        """
        if self.pool:
            client = self.pool.pop()
            logger.debug("ollama_client_from_pool", pool_remaining=len(self.pool))
            return client

        # Create new client
        client = ollama.Client(host=self.host)
        logger.debug("ollama_client_created", host=self.host)

        # Warm up connection by listing models
        try:
            client.list()
            logger.debug("ollama_client_warmup_success")
        except Exception as e:
            logger.warning("ollama_client_warmup_failed", error=str(e))

        return client

    def return_client(self, client: ollama.Client):
        """Return client to pool

        Args:
            client: Ollama client to return to pool
        """
        if len(self.pool) < self.pool_size:
            self.pool.append(client)
            logger.debug("ollama_client_returned_to_pool", pool_size=len(self.pool))
        else:
            logger.debug("ollama_client_discarded", reason="pool_full")

    def get_stats(self) -> dict:
        """Get pool statistics

        Returns:
            Dictionary with pool stats
        """
        return {
            "pool_size": self.pool_size,
            "available": len(self.pool),
            "in_use": self.pool_size - len(self.pool),
        }


# Global pool singleton
_ollama_pool = OllamaPool(pool_size=3)


def get_ollama_client() -> ollama.Client:
    """Get an Ollama client from the pool

    Returns:
        ollama.Client instance
    """
    return _ollama_pool.get_client()


def return_ollama_client(client: ollama.Client):
    """Return an Ollama client to the pool

    Args:
        client: Client to return
    """
    _ollama_pool.return_client(client)


def get_pool_stats() -> dict:
    """Get Ollama pool statistics

    Returns:
        Dictionary with pool stats
    """
    return _ollama_pool.get_stats()
