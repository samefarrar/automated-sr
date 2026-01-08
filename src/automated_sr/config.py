"""Configuration management for the systematic review tool."""

import os
from pathlib import Path

from pydantic import BaseModel, Field


class ZoteroConfig(BaseModel):
    """Zotero connection settings."""

    library_id: str | None = None
    library_type: str = "user"  # 'user' or 'group'
    api_key: str | None = None
    local: bool = True  # Use local Zotero API (requires Zotero 7+ running)


class Config(BaseModel):
    """Global configuration for the systematic review tool."""

    # API settings
    anthropic_api_key: str | None = Field(default=None)
    default_model: str = "claude-sonnet-4-20250514"

    # Zotero settings
    zotero: ZoteroConfig = Field(default_factory=ZoteroConfig)

    # Paths
    data_dir: Path = Field(default_factory=lambda: Path.cwd() / ".sr_data")
    database_path: Path | None = None

    # Screening settings
    screen_batch_size: int = 10  # Number of citations to process in parallel
    max_retries: int = 3  # Retries for API calls

    def __init__(self, **data: object) -> None:
        super().__init__(**data)

        # Load API key from environment if not provided
        if self.anthropic_api_key is None:
            self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")

        # Load Zotero settings from environment if not provided
        if self.zotero.library_id is None:
            self.zotero.library_id = os.environ.get("ZOTERO_LIBRARY_ID")
        if self.zotero.api_key is None:
            self.zotero.api_key = os.environ.get("ZOTERO_API_KEY")

        # Set default database path
        if self.database_path is None:
            self.database_path = self.data_dir / "reviews.db"

    def ensure_data_dir(self) -> None:
        """Create the data directory if it doesn't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)


# Global config instance
_config: Config | None = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def set_config(config: Config) -> None:
    """Set the global configuration instance."""
    global _config
    _config = config
