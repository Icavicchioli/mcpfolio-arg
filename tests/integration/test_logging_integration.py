"""Integration tests for logging across modules"""

import sys
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.mark.integration
def test_logging_imports_in_all_modules():
    """Test logging is properly imported in all modules"""
    # Test main.py
    import main

    assert hasattr(main, "logger")

    # Test finance.py
    from server import finance

    assert hasattr(finance, "logger")


@pytest.mark.integration
def test_log_file_creation():
    """Test log file is created and writable"""
    from pathlib import Path

    from logging_config import get_logger

    log_file = Path("logs/quant-ollama.log")
    logger = get_logger("test_integration")

    logger.info("integration_test_message", component="test")

    assert log_file.exists()
    assert log_file.stat().st_size > 0


@pytest.mark.integration
def test_request_correlation_across_modules():
    """Test request IDs work across module boundaries"""
    from logging_config import get_request_id, start_request

    req_id = start_request()

    # Should be accessible from any module
    assert get_request_id() == req_id
    assert len(req_id) == 8  # Short ID format
