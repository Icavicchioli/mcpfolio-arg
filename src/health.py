"""
System health checks for validating dependencies and configuration.

Provides quick, non-blocking health checks for:
- Python version
- Ollama installation and server status
- Model availability
- MCP server existence
- Configuration validity
"""

import subprocess  # nosec
import sys
from dataclasses import dataclass
from pathlib import Path

from src.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class HealthCheckResult:
    """Result of a health check"""

    name: str
    passed: bool
    message: str
    duration_ms: float = 0.0


class HealthCheck:
    """System health validation utilities"""

    @staticmethod
    def check_python_version() -> tuple[bool, str]:
        """Verify Python 3.11+

        Returns:
            Tuple of (passed, message)
        """
        version = sys.version_info
        if version.major >= 3 and version.minor >= 11:
            return True, f"Python {version.major}.{version.minor}.{version.micro}"
        return False, f"Python {version.major}.{version.minor} (need 3.11+)"

    @staticmethod
    def check_ollama_installed() -> tuple[bool, str]:
        """Check if Ollama is installed

        Returns:
            Tuple of (passed, message)
        """
        try:
            result = subprocess.run(
                ["ollama", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )  # nosec
            if result.returncode == 0:
                return True, result.stdout.strip()
            return False, "Ollama command failed"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False, "Not installed - download from ollama.ai"

    @staticmethod
    def check_ollama_running() -> tuple[bool, str]:
        """Check if Ollama server is running

        Returns:
            Tuple of (passed, message)
        """
        try:
            result = subprocess.run(
                ["ollama", "list"], capture_output=True, timeout=5, check=False
            )  # nosec
            if result.returncode == 0:
                return True, "Server running"
            return False, "Server not responding"
        except subprocess.TimeoutExpired:
            return False, "Server not responding - run 'ollama serve'"

    @staticmethod
    def check_model_downloaded(model: str = "llama3.2:3b") -> tuple[bool, str]:
        """Check if required model is downloaded

        Args:
            model: Model name to check

        Returns:
            Tuple of (passed, message)
        """
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )  # nosec
            if result.returncode == 0 and model in result.stdout:
                return True, f"{model} available"
            return False, f"Run: ollama pull {model}"
        except subprocess.TimeoutExpired:
            return False, "Cannot check - Ollama not responding"

    @staticmethod
    def check_mcp_server_exists(path: str | Path) -> tuple[bool, str]:
        """Verify MCP server file exists

        Args:
            path: Path to MCP server

        Returns:
            Tuple of (passed, message)
        """
        path = Path(path)
        if path.exists():
            return True, f"Found at {path}"
        return False, f"Missing: {path}"

    @staticmethod
    def run_all_checks(model: str = "llama3.2:3b") -> dict:
        """Run all health checks and return results

        Args:
            model: Model name to check

        Returns:
            Dictionary with check results
        """
        import time

        from src.config import get_settings

        settings = get_settings()
        start = time.time()

        checks = []

        # Python version
        check_start = time.time()
        passed, message = HealthCheck.check_python_version()
        checks.append(
            HealthCheckResult(
                name="Python Version",
                passed=passed,
                message=message,
                duration_ms=(time.time() - check_start) * 1000,
            )
        )

        # Ollama installed
        check_start = time.time()
        passed, message = HealthCheck.check_ollama_installed()
        checks.append(
            HealthCheckResult(
                name="Ollama Installed",
                passed=passed,
                message=message,
                duration_ms=(time.time() - check_start) * 1000,
            )
        )

        # Ollama running
        check_start = time.time()
        passed, message = HealthCheck.check_ollama_running()
        checks.append(
            HealthCheckResult(
                name="Ollama Running",
                passed=passed,
                message=message,
                duration_ms=(time.time() - check_start) * 1000,
            )
        )

        # Model available
        check_start = time.time()
        passed, message = HealthCheck.check_model_downloaded(model)
        checks.append(
            HealthCheckResult(
                name="Model Available",
                passed=passed,
                message=message,
                duration_ms=(time.time() - check_start) * 1000,
            )
        )

        # MCP server exists
        check_start = time.time()
        passed, message = HealthCheck.check_mcp_server_exists(settings.mcp_server_path)
        checks.append(
            HealthCheckResult(
                name="MCP Server",
                passed=passed,
                message=message,
                duration_ms=(time.time() - check_start) * 1000,
            )
        )

        total_duration = (time.time() - start) * 1000

        return {
            "all_passed": all(c.passed for c in checks),
            "checks": checks,
            "total_duration_ms": total_duration,
        }
