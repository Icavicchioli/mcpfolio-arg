"""Robustness wrappers for MCP tools."""

import functools
import time
from collections.abc import Callable

import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = structlog.get_logger(__name__)


def with_retry(max_attempts: int = 3, backoff_seconds: int = 2):
    """Decorator for retry logic with exponential backoff."""

    def decorator(func: Callable):
        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=backoff_seconds, min=1, max=10),
            retry=retry_if_exception_type((Exception,)),  # yfinance can throw various exceptions
            reraise=True,
        )
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator


def circuit_breaker(failure_threshold: int = 5, timeout_seconds: int = 60):
    """Simple circuit breaker pattern for external APIs."""

    class BreakerState:
        def __init__(self):
            self.failures = 0
            self.last_failure_time = 0.0
            self.is_open = False

    state = BreakerState()

    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if state.is_open:
                if time.time() - state.last_failure_time > timeout_seconds:
                    state.is_open = False
                    state.failures = 0
                    logger.info("circuit_breaker_half_open", tool=func.__name__)
                else:
                    logger.warning("circuit_breaker_open", tool=func.__name__)
                    return {
                        "error": "Circuit breaker is open due to repeated failures. Please try again later.",
                        "error_type": "circuit_breaker",
                    }

            try:
                result = func(*args, **kwargs)
                state.failures = 0
                return result
            except Exception as e:
                state.failures += 1
                state.last_failure_time = time.time()
                if state.failures >= failure_threshold:
                    state.is_open = True
                    logger.error(
                        "circuit_breaker_opened", tool=func.__name__, failures=state.failures
                    )
                raise e

        return wrapper

    return decorator
