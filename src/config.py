"""Application configuration with environment variable support using Pydantic Settings."""

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application configuration with environment variable support.

    All settings can be overridden via environment variables with MCPFOLIO_ prefix.
    Example: MCPFOLIO_OLLAMA_MODEL=llama3.2:3b
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MCPFOLIO_",
        case_sensitive=False,
        extra="ignore",
    )

    # ==========================================================================
    # Environment
    # ==========================================================================
    environment: Literal["development", "staging", "production"] = Field(
        default="development", description="Application environment"
    )

    # ==========================================================================
    # Ollama Configuration
    # ==========================================================================
    ollama_model: str = Field(
        default="llama3.2:3b", description="Ollama model to use for inference"
    )

    ollama_host: str = Field(
        default="http://localhost:11434",
        description="Ollama server URL",
    )

    ollama_timeout: int = Field(
        default=120, ge=1, le=600, description="Ollama request timeout in seconds"
    )

    ollama_temperature: float = Field(
        default=0.7, ge=0.0, le=2.0, description="LLM temperature for response generation"
    )

    # ==========================================================================
    # MCP Server Configuration
    # ==========================================================================
    mcp_transport: Literal["stdio", "sse"] = Field(
        default="stdio", description="MCP transport protocol"
    )

    mcp_server_path: str = Field(
        default="", description="Path to MCP server (auto-detected if empty)"
    )

    # ==========================================================================
    # yfinance Configuration
    # ==========================================================================
    yfinance_rate_limit: int = Field(
        default=5, ge=1, le=100, description="Max yfinance requests per second"
    )

    yfinance_timeout: int = Field(
        default=30, ge=1, le=300, description="yfinance request timeout in seconds"
    )

    yfinance_cache_ttl: int = Field(
        default=300, ge=0, le=3600, description="yfinance cache TTL in seconds (0 = disabled)"
    )

    # ==========================================================================
    # Logging Configuration
    # ==========================================================================
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Logging level"
    )

    log_file: str = Field(default="logs/mcpfolio.log", description="Log file path")

    log_max_bytes: int = Field(
        default=10_000_000,
        ge=1_000_000,
        le=100_000_000,
        description="Max log file size in bytes before rotation",
    )

    log_backup_count: int = Field(
        default=5, ge=0, le=20, description="Number of log backup files to keep"
    )

    log_json_format: bool = Field(
        default=True, description="Use JSON format for logs (vs human-readable)"
    )

    # ==========================================================================
    # Performance Configuration
    # ==========================================================================
    max_context_tokens: int = Field(
        default=128_000,
        ge=1_000,
        le=1_000_000,
        description="Maximum LLM context size in tokens",
    )

    cold_start_timeout: int = Field(
        default=5, ge=1, le=60, description="Maximum startup time in seconds"
    )

    # ==========================================================================
    # Data Persistence
    # ==========================================================================
    data_dir: str = Field(default="data", description="Directory for persistent data storage")

    enable_caching: bool = Field(default=True, description="Enable response caching")

    # ==========================================================================
    # Security (for future API endpoints)
    # ==========================================================================
    api_key: str = Field(default="", description="API authentication key (optional)")

    enable_cors: bool = Field(default=False, description="Enable CORS for API endpoints")

    allowed_origins: list[str] = Field(
        default_factory=list, description="List of allowed CORS origins"
    )

    # ==========================================================================
    # Validators
    # ==========================================================================

    @field_validator("mcp_server_path", mode="before")
    @classmethod
    def set_default_server_path(cls, v: str) -> str:
        """Set default MCP server path if not provided."""
        if not v:
            # Auto-detect server path relative to this file
            config_dir = Path(__file__).parent
            server_path = config_dir / "server" / "finance.py"
            return str(server_path.absolute())
        return v

    @field_validator("data_dir", mode="after")
    @classmethod
    def create_data_dir(cls, v: str) -> str:
        """Ensure data directory exists."""
        Path(v).mkdir(parents=True, exist_ok=True)
        return v

    @field_validator("log_file", mode="after")
    @classmethod
    def create_log_dir(cls, v: str) -> str:
        """Ensure log directory exists."""
        Path(v).parent.mkdir(parents=True, exist_ok=True)
        return v

    # ==========================================================================
    # Helper Methods
    # ==========================================================================

    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == "production"

    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.environment == "development"

    def get_ollama_config(self) -> dict:
        """Get Ollama configuration as a dictionary."""
        return {
            "model": self.ollama_model,
            "base_url": self.ollama_host,
            "timeout": self.ollama_timeout,
            "temperature": self.ollama_temperature,
        }

    def get_log_config(self) -> dict:
        """Get logging configuration as a dictionary."""
        return {
            "log_level": self.log_level,
            "log_file": self.log_file,
            "max_bytes": self.log_max_bytes,
            "backup_count": self.log_backup_count,
            "json_logs": self.log_json_format,
        }


# =============================================================================
# Global Settings Instance
# =============================================================================

_settings: Settings | None = None


def get_settings() -> Settings:
    """
    Get the global settings instance.

    This function implements a singleton pattern to ensure only one
    settings instance exists throughout the application lifecycle.

    Returns:
        Settings: The global settings instance
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """
    Reload settings from environment.

    Useful for testing or when environment variables change.

    Returns:
        Settings: A new settings instance
    """
    global _settings
    _settings = Settings()
    return _settings


# Export for convenience
settings = get_settings()
