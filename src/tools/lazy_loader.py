# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Adam Karp
"""
Lazy loading MCP client for faster startup.

Instead of loading MCP tools at startup, they are loaded on first use.
This reduces startup time from ~8-10s to <3s.
"""

import asyncio
import os
import sys
from typing import Any, cast

from src.logging_config import get_logger

logger = get_logger(__name__)

_EXPECTED_ENV = "mcpfolio"


def _check_conda_env() -> None:
    active_env = os.environ.get("CONDA_DEFAULT_ENV", "")
    # conda run doesn't always set CONDA_DEFAULT_ENV, so also check the executable path
    exe_in_env = _EXPECTED_ENV in sys.executable.replace("\\", "/")
    if active_env == _EXPECTED_ENV or exe_in_env:
        logger.info("conda_env_ok", env=active_env or "(via executable)", python=sys.executable)
    else:
        logger.warning(
            "wrong_conda_env",
            expected=_EXPECTED_ENV,
            active=active_env or "(none)",
            python=sys.executable,
        )


_check_conda_env()


class LazyMCPClient:
    """Lazy-loading MCP client - only connects on first tool use"""

    def __init__(self):
        self._client = None
        self._tools = None
        self._lock = asyncio.Lock()
        logger.info("lazy_mcp_client_initialized")

    async def get_tools(self):
        """Get tools, loading client on first access"""
        if self._tools is not None:
            logger.debug("mcp_tools_cache_hit")
            return self._tools

        async with self._lock:
            if self._tools is None:  # Double-check after acquiring lock
                logger.info("mcp_tools_loading_started")
                from langchain_mcp_adapters.client import MultiServerMCPClient

                from src.config import get_settings

                settings = get_settings()
                self._client = MultiServerMCPClient(
                    {
                        "finance": {
                            "command": sys.executable,
                            "args": [settings.mcp_server_path],
                            "transport": cast(Any, settings.mcp_transport),
                        }
                    }
                )
                self._tools = await self._client.get_tools()
                logger.info(
                    "mcp_tools_loaded",
                    tool_count=len(self._tools),
                    tool_names=[t.name for t in self._tools],
                )

            return self._tools

    async def close(self):
        """Close the MCP client connection"""
        if self._client:
            logger.info("mcp_client_closing")
            # Add any cleanup logic if needed
            self._client = None
            self._tools = None


# Global lazy client singleton
_lazy_client = LazyMCPClient()


async def get_mcp_tools():
    """Get MCP tools (lazy-loaded)

    Returns:
        List of MCP tool definitions
    """
    return await _lazy_client.get_tools()


async def get_mcp_client():
    """Get the MCP client instance

    Returns:
        LazyMCPClient instance
    """
    # Ensure tools are loaded
    await _lazy_client.get_tools()
    return _lazy_client


async def close_mcp_client():
    """Close the MCP client connection"""
    await _lazy_client.close()
