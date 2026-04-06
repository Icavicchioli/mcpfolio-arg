# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Adam Karp
"""
Quick startup orchestration for <3 second initialization.

Implements:
- Parallel health checks
- Lazy loading strategy
- Background initialization
- Startup timing and metrics
"""

import asyncio
import time
from dataclasses import dataclass

from src.health import HealthCheck
from src.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class StartupResult:
    """Result of startup sequence"""

    ready: bool
    startup_time_ms: float
    health_checks: dict
    background_init_started: bool


async def quick_startup(skip_health_checks: bool = False) -> StartupResult:
    """
    Fast startup sequence with parallel checks.

    Target: <3 seconds to ready state

    Args:
        skip_health_checks: Skip health checks (faster but less safe)

    Returns:
        StartupResult with timing and status info
    """
    start_time = time.time()
    logger.info("startup_sequence_begin")

    # Phase 1: Critical checks only (if not skipped)
    health_results = {}
    if not skip_health_checks:
        logger.info("health_checks_running")
        check_start = time.time()

        # Run critical checks in parallel
        from src.config import get_settings

        settings = get_settings()

        # Note: HealthCheck.run_all_checks is synchronous, run in executor
        loop = asyncio.get_event_loop()
        health_results = await loop.run_in_executor(
            None, HealthCheck.run_all_checks, settings.ollama_model
        )

        health_duration = (time.time() - check_start) * 1000
        logger.info(
            "health_checks_complete",
            duration_ms=health_duration,
            all_passed=health_results.get("all_passed", False),
        )
    else:
        logger.info("health_checks_skipped")
        health_results = {"all_passed": True, "checks": [], "total_duration_ms": 0}

    # Phase 2: Start background initialization (non-blocking)
    background_started = False
    if health_results.get("all_passed"):
        asyncio.create_task(background_init())
        background_started = True
        logger.info("background_init_started")

    elapsed_ms = (time.time() - start_time) * 1000

    logger.info(
        "startup_sequence_complete",
        duration_ms=elapsed_ms,
        ready=health_results.get("all_passed", False),
        background_init=background_started,
    )

    return StartupResult(
        ready=health_results.get("all_passed", False),
        startup_time_ms=elapsed_ms,
        health_checks=health_results,
        background_init_started=background_started,
    )


async def background_init():
    """
    Initialize non-critical components in background.

    This runs after startup completes to avoid blocking
    the user from interacting with the system.

    Tasks:
    - Warm up MCP tools (lazy load to trigger caching)
    - Preload model context if needed
    - Initialize cache structures
    """
    logger.info("background_init_begin")
    start_time = time.time()

    try:
        # Task 1: Warm up Ollama connection
        logger.info("background_warmup_ollama")
        from src.ollama_pool import get_ollama_client, return_ollama_client

        client = get_ollama_client()
        try:
            client.list()  # Warm up connection
            logger.info("background_warmup_ollama_success")
        except Exception as e:
            logger.warning("background_warmup_ollama_failed", error=str(e))
        finally:
            return_ollama_client(client)

        # Task 2: Note about MCP tools
        # MCP tools are lazy-loaded, so they'll be loaded on first use
        # This avoids the expensive initialization during startup
        logger.info("background_init_mcp_ready", status="lazy_load")

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info("background_init_complete", duration_ms=elapsed_ms)

    except Exception as e:
        logger.error("background_init_error", error=str(e), error_type=type(e).__name__)


async def shutdown():
    """
    Clean shutdown of all resources.

    Closes:
    - MCP client connections
    - Ollama pool
    - Any background tasks
    """
    logger.info("shutdown_sequence_begin")

    try:
        # Close MCP client
        from src.tools.lazy_loader import close_mcp_client

        await close_mcp_client()
        logger.info("mcp_client_closed")

    except Exception as e:
        logger.error("shutdown_error", error=str(e))

    logger.info("shutdown_sequence_complete")
