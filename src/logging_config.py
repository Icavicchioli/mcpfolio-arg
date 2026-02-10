"""
Structured logging configuration for Quant-Ollama-Analyst

Uses structlog for structured, JSON-formatted logs with:
- Request correlation IDs
- Rotating file handlers
- Console output for development
- Performance timing
"""

import logging
import sys
import uuid
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path

import structlog

# Context variable for request correlation
request_id: ContextVar[str] = ContextVar("request_id", default="")


def start_request() -> str:
    """
    Start a new request and generate correlation ID

    Returns:
        str: Generated request ID for tracing
    """
    req_id = str(uuid.uuid4())[:8]  # Short ID for readability
    request_id.set(req_id)
    return req_id


def get_request_id() -> str:
    """Get current request ID"""
    return request_id.get() or "no-request"


def add_request_id(logger, method_name, event_dict):
    """Processor to add request_id to all log entries"""
    event_dict["request_id"] = get_request_id()
    return event_dict


def add_timestamp(logger, method_name, event_dict):
    """Add ISO timestamp to log entries"""
    from datetime import datetime

    event_dict["timestamp"] = datetime.utcnow().isoformat() + "Z"
    return event_dict


def setup_logging(
    log_level: str | None = None,
    log_file: str | None = None,
    max_bytes: int | None = None,
    backup_count: int | None = None,
    enable_console: bool = True,
    json_logs: bool | None = None,
) -> None:
    """
    Configure structured logging for the application.

    If parameters are None, will attempt to load from settings.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file
        max_bytes: Max log file size before rotation
        backup_count: Number of backup files to keep
        enable_console: Whether to log to console
        json_logs: Whether to use JSON format (vs. human-readable)
    """
    # Load from settings if available and parameters not provided
    try:
        from config import get_settings

        settings = get_settings()
        log_config = settings.get_log_config()

        log_level = log_level or log_config["log_level"]
        log_file = log_file or log_config["log_file"]
        max_bytes = max_bytes or log_config["max_bytes"]
        backup_count = backup_count or log_config["backup_count"]
        json_logs = json_logs if json_logs is not None else log_config["json_logs"]
    except ImportError:
        # Settings not available, use defaults
        log_level = log_level or "INFO"
        log_file = log_file or "logs/quant-ollama.log"
        max_bytes = max_bytes or 10_000_000
        backup_count = backup_count or 5
        json_logs = json_logs if json_logs is not None else True

    # Create logs directory if it doesn't exist
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert log level string to constant
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Configure standard library logging
    logging.basicConfig(format="%(message)s", level=numeric_level, handlers=[])

    # Remove existing handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    # File handler with rotation
    file_handler = RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setLevel(numeric_level)

    # Console handler for development
    if enable_console:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(numeric_level)
        root_logger.addHandler(console_handler)

    root_logger.addHandler(file_handler)

    # Configure structlog processors
    processors = [
        structlog.stdlib.filter_by_level,
        add_request_id,
        add_timestamp,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_logs:
        # JSON output for production
        processors.append(structlog.processors.JSONRenderer())
    else:
        # Human-readable output for development
        processors.extend([structlog.dev.ConsoleRenderer(colors=True)])

    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """
    Get a logger instance

    Args:
        name: Logger name (usually __name__)

    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)


# Convenience function for timing operations
class LogTimer:
    """Context manager for timing operations with logging"""

    def __init__(self, logger: structlog.BoundLogger, operation: str, **extra):
        self.logger = logger
        self.operation = operation
        self.extra = extra
        self.start_time = None

    def __enter__(self):
        import time

        self.start_time = time.time()
        self.logger.info(f"{self.operation}_started", operation=self.operation, **self.extra)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        import time

        duration_ms = (time.time() - self.start_time) * 1000

        if exc_type is None:
            self.logger.info(
                f"{self.operation}_completed",
                operation=self.operation,
                duration_ms=round(duration_ms, 2),
                success=True,
                **self.extra,
            )
        else:
            self.logger.error(
                f"{self.operation}_failed",
                operation=self.operation,
                duration_ms=round(duration_ms, 2),
                success=False,
                error=str(exc_val),
                error_type=exc_type.__name__,
                **self.extra,
            )

        return False  # Don't suppress exceptions


# Initialize default logging when module is imported
# Can be reconfigured by calling setup_logging() with different parameters
setup_logging()
