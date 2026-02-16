"""Unit tests for configuration system"""

from pathlib import Path

import pytest


def test_settings_default_values():
    """Test settings load with default values"""
    from config import Settings

    settings = Settings()

    assert settings.environment == "development"
    assert settings.ollama_model == "llama3.2:3b"
    assert settings.ollama_host == "http://localhost:11434"
    assert settings.log_level == "INFO"
    assert settings.enable_caching is True


def test_settings_from_env_vars(monkeypatch):
    """Test settings can be overridden via environment variables"""
    from config import reload_settings

    # Set environment variables
    monkeypatch.setenv("MCPFOLIO_ENVIRONMENT", "production")
    monkeypatch.setenv("MCPFOLIO_OLLAMA_MODEL", "llama3.2:1b")
    monkeypatch.setenv("MCPFOLIO_LOG_LEVEL", "DEBUG")

    # Reload settings to pick up env vars
    settings = reload_settings()

    assert settings.environment == "production"
    assert settings.ollama_model == "llama3.2:1b"
    assert settings.log_level == "DEBUG"


def test_get_ollama_config():
    """Test get_ollama_config helper method"""
    from config import Settings

    settings = Settings()
    config = settings.get_ollama_config()

    assert "model" in config
    assert "base_url" in config
    assert "timeout" in config
    assert "temperature" in config
    assert config["model"] == settings.ollama_model


def test_get_log_config():
    """Test get_log_config helper method"""
    from config import Settings

    settings = Settings()
    log_config = settings.get_log_config()

    assert "log_level" in log_config
    assert "log_file" in log_config
    assert "max_bytes" in log_config
    assert "backup_count" in log_config
    assert "json_logs" in log_config


def test_is_production():
    """Test is_production helper method"""
    from config import Settings

    dev_settings = Settings(environment="development")
    assert dev_settings.is_production() is False

    prod_settings = Settings(environment="production")
    assert prod_settings.is_production() is True


def test_is_development():
    """Test is_development helper method"""
    from config import Settings

    dev_settings = Settings(environment="development")
    assert dev_settings.is_development() is True

    prod_settings = Settings(environment="production")
    assert prod_settings.is_development() is False


def test_mcp_server_path_auto_detection():
    """Test MCP server path is auto-detected when not provided"""
    from config import Settings

    settings = Settings(mcp_server_path="")

    assert settings.mcp_server_path != ""
    assert "finance.py" in settings.mcp_server_path
    assert Path(settings.mcp_server_path).exists()


def test_data_dir_creation():
    """Test data directory is created if it doesn't exist"""
    import tempfile

    from config import Settings

    with tempfile.TemporaryDirectory() as tmpdir:
        test_data_dir = Path(tmpdir) / "test_data"

        Settings(data_dir=str(test_data_dir))

        assert test_data_dir.exists()
        assert test_data_dir.is_dir()


def test_validation_constraints():
    """Test Pydantic validation constraints"""
    from pydantic import ValidationError

    from config import Settings

    # Test temperature bounds
    with pytest.raises(ValidationError):  # Pydantic ValidationError
        Settings(ollama_temperature=3.0)  # > 2.0

    with pytest.raises(ValidationError):
        Settings(ollama_temperature=-1.0)  # < 0.0

    # Test timeout bounds
    with pytest.raises(ValidationError):
        Settings(ollama_timeout=700)  # > 600

    # Test log level options
    with pytest.raises(ValidationError):
        Settings(log_level="INVALID")


def test_singleton_pattern():
    """Test get_settings returns same instance"""
    from config import get_settings

    settings1 = get_settings()
    settings2 = get_settings()

    assert settings1 is settings2


def test_reload_settings_creates_new_instance():
    """Test reload_settings creates a new instance"""
    from config import get_settings, reload_settings

    settings1 = get_settings()
    settings2 = reload_settings()

    assert settings1 is not settings2
