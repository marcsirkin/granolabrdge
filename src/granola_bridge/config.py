"""Configuration loading from environment and YAML files."""

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GranolaConfig(BaseModel):
    cache_path: str = "~/Library/Application Support/Granola/cache-v3.json"
    watch_debounce_ms: int = 500


class LLMConfig(BaseModel):
    base_url: str = "http://localhost:1234/v1"
    model: str = "local-model"
    timeout_seconds: int = 120


class TrelloConfig(BaseModel):
    api_base_url: str = "https://api.trello.com/1"


class RetryConfig(BaseModel):
    max_attempts: int = 5
    base_delay_seconds: int = 30


class WebConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8080


class DailySummaryConfig(BaseModel):
    enabled: bool = True
    time: str = "09:00"


class NotificationsConfig(BaseModel):
    daily_summary: DailySummaryConfig = Field(default_factory=DailySummaryConfig)


class DatabaseConfig(BaseModel):
    path: str = "~/.granola-bridge/bridge.db"


class EnvSettings(BaseSettings):
    """Environment variables (secrets)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    trello_api_key: str = ""
    trello_api_token: str = ""
    trello_list_id: str = ""
    slack_webhook_url: Optional[str] = None
    discord_webhook_url: Optional[str] = None


class AppConfig(BaseModel):
    """Combined application configuration."""

    granola: GranolaConfig = Field(default_factory=GranolaConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    trello: TrelloConfig = Field(default_factory=TrelloConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)

    # Environment settings (secrets)
    env: EnvSettings = Field(default_factory=EnvSettings)

    def get_granola_cache_path(self) -> Path:
        """Get expanded Granola cache path."""
        return Path(self.granola.cache_path).expanduser()

    def get_database_path(self) -> Path:
        """Get expanded database path."""
        return Path(self.database.path).expanduser()


def load_config(config_path: Optional[Path] = None) -> AppConfig:
    """Load configuration from YAML file and environment variables.

    Args:
        config_path: Path to config.yaml. If None, looks in current directory
                    and ~/.granola-bridge/

    Returns:
        AppConfig instance with merged configuration
    """
    yaml_config = {}

    # Search for config file
    search_paths = [
        config_path,
        Path("config.yaml"),
        Path.home() / ".granola-bridge" / "config.yaml",
    ]

    for path in search_paths:
        if path and path.exists():
            with open(path) as f:
                yaml_config = yaml.safe_load(f) or {}
            break

    # Load environment variables
    env_settings = EnvSettings()

    # Build config with YAML values
    config_data = {
        "granola": yaml_config.get("granola", {}),
        "llm": yaml_config.get("llm", {}),
        "trello": yaml_config.get("trello", {}),
        "retry": yaml_config.get("retry", {}),
        "web": yaml_config.get("web", {}),
        "notifications": yaml_config.get("notifications", {}),
        "database": yaml_config.get("database", {}),
        "env": env_settings,
    }

    return AppConfig(**config_data)


# Global config instance (lazy loaded)
_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def set_config(config: AppConfig) -> None:
    """Set the global configuration instance (for testing)."""
    global _config
    _config = config
