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

    # LLM API settings
    anthropic_api_key: str | None = Field(default=None)
    openai_api_key: str | None = Field(default=None)
    openrouter_api_key: str | None = Field(default=None)
    default_model: str = "claude-sonnet-4-5-20250929"

    # OpenAlex settings
    openalex_email: str | None = Field(default=None)

    # Zotero settings
    zotero: ZoteroConfig = Field(default_factory=ZoteroConfig)

    # Paths
    data_dir: Path = Field(default_factory=lambda: Path.cwd() / ".sr_data")
    database_path: Path | None = None
    pdf_download_dir: Path | None = None

    # Screening settings
    screen_batch_size: int = 10  # Number of citations to process in parallel
    max_retries: int = 3  # Retries for API calls

    def __init__(self, **data: object) -> None:
        super().__init__(**data)

        # Load API keys from environment if not provided
        if self.anthropic_api_key is None:
            self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
        if self.openai_api_key is None:
            self.openai_api_key = os.environ.get("OPENAI_API_KEY")
        if self.openrouter_api_key is None:
            self.openrouter_api_key = os.environ.get("OPENROUTER_API_KEY")

        # Load OpenAlex email from environment
        if self.openalex_email is None:
            self.openalex_email = os.environ.get("OPENALEX_EMAIL")

        # Load Zotero settings from environment if not provided
        if self.zotero.library_id is None:
            self.zotero.library_id = os.environ.get("ZOTERO_LIBRARY_ID")
        if self.zotero.api_key is None:
            self.zotero.api_key = os.environ.get("ZOTERO_API_KEY")

        # Set default paths
        if self.database_path is None:
            self.database_path = self.data_dir / "reviews.db"
        if self.pdf_download_dir is None:
            self.pdf_download_dir = self.data_dir / "pdfs"

    def ensure_data_dir(self) -> None:
        """Create the data directory if it doesn't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def ensure_pdf_dir(self) -> None:
        """Create the PDF download directory if it doesn't exist."""
        if self.pdf_download_dir:
            self.pdf_download_dir.mkdir(parents=True, exist_ok=True)


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


def get_zotero_config() -> ZoteroConfig:
    """Get the Zotero configuration from the global config."""
    return get_config().zotero
