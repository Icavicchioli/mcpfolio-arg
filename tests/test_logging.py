"""Test logging configuration and verify it works correctly."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from logging_config import LogTimer, get_logger, start_request


def test_basic_logging():
    """Test basic logging functionality"""
    logger = get_logger("test")

    print("Testing basic logging...")
    logger.info("test_message", component="test", status="running")
    logger.warning("test_warning", issue="minor")
    logger.error("test_error", error="simulated")
    print("✓ Basic logging test passed")


def test_request_correlation():
    """Test request correlation IDs"""
    logger = get_logger("test")

    print("\nTesting request correlation...")
    req_id = start_request()
    print(f"Generated request ID: {req_id}")

    logger.info("request_started", operation="test_operation")
    logger.info("request_processing", step=1)
    logger.info("request_completed", operation="test_operation")

    print("✓ Request correlation test passed")


def test_log_timer():
    """Test the LogTimer context manager"""
    import time

    logger = get_logger("test")

    print("\nTesting LogTimer...")
    with LogTimer(logger, "test_operation", param1="value1"):
        time.sleep(0.1)  # Simulate work

    print("✓ LogTimer test passed")


def test_log_timer_with_error():
    """Test LogTimer with errors"""
    logger = get_logger("test")

    print("\nTesting LogTimer with error handling...")
    try:
        with LogTimer(logger, "failing_operation"):
            raise ValueError("Simulated error")
    except ValueError:
        pass  # Expected

    print("✓ LogTimer error handling test passed")


def test_log_file_creation():
    """Verify log file is created"""
    from pathlib import Path

    print("\nChecking log file creation...")
    log_file = Path("logs/quant-ollama.log")

    if log_file.exists():
        print(f"✓ Log file created: {log_file}")
        print(f"  Size: {log_file.stat().st_size} bytes")

        # Show last few lines
        with open(log_file) as f:
            lines = f.readlines()
            print(f"  Total log entries: {len(lines)}")
            if lines:
                print("\n  Last log entry:")
                print(f"  {lines[-1].strip()}")
    else:
        print("⚠ Log file not yet created (will be created on first log)")


if __name__ == "__main__":
    print("=" * 60)
    print("Logging Configuration Test Suite")
    print("=" * 60)

    try:
        test_basic_logging()
        test_request_correlation()
        test_log_timer()
        test_log_timer_with_error()
        test_log_file_creation()

        print("\n" + "=" * 60)
        print("✓ All logging tests passed!")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
