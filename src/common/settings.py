"""Darwin settings — single source of truth for configuration.

Priority (highest wins):
  1. Environment variables (including values loaded from a ``.env`` file)
  2. JSON config (``config/agent_config.json`` by default, overridable via
     the ``DARWIN_CONFIG`` env var)
  3. Code defaults defined below

The JSON file is what humans edit for day-to-day LLM/prompt tuning. Secrets
(OpenAI key, Obsidian API key) live in ``.env`` so they never land in git.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class DarwinSettings(BaseSettings):
    """All runtime configuration, validated and typed."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        # `model_name` clashes with pydantic's default `model_` protected prefix;
        # rename the protected namespace so our field names survive unchanged.
        protected_namespaces=("settings_",),
    )

    # --- Paths ------------------------------------------------------------
    project_root: Path = PROJECT_ROOT
    paper_storage: Path = Field(
        default=PROJECT_ROOT / "papers",
        validation_alias="PAPER_STORAGE",
    )
    research_log_db: Path = Field(
        default=PROJECT_ROOT / "research_log.db",
        validation_alias="RESEARCH_LOG_DB",
    )
    log_dir: Path = Field(
        default=PROJECT_ROOT / "logs",
        validation_alias="DARWIN_LOG_DIR",
    )

    # --- LLM --------------------------------------------------------------
    provider: Literal["ollama", "openai"] = "ollama"
    model_name: str = "llama3.1"
    api_base: str = "http://localhost:11434"
    temperature: float = 0.7
    system_prompt: str = ""
    openai_api_key: Optional[str] = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
    )

    # --- Obsidian ---------------------------------------------------------
    obsidian_vault_path: Optional[Path] = Field(
        default=None,
        validation_alias="OBSIDIAN_VAULT_PATH",
    )
    obsidian_api_key: Optional[str] = Field(
        default=None,
        validation_alias="OBSIDIAN_API_KEY",
    )
    obsidian_port: int = Field(default=27123, validation_alias="OBSIDIAN_PORT")
    obsidian_default_folder: str = Field(
        default="Research/Incoming",
        validation_alias="DEFAULT_FOLDER",
    )

    # --- arXiv ------------------------------------------------------------
    arxiv_rate_limit_seconds: float = 3.0
    arxiv_max_retries: int = 3
    arxiv_page_size: int = 100

    # --- Logging ----------------------------------------------------------
    log_level: str = Field(default="INFO", validation_alias="DARWIN_LOG_LEVEL")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        # Flip init vs env priority: env vars should always win over JSON-sourced
        # init kwargs, so that operators can override config without editing the
        # shared JSON file. Default pydantic-settings order is init > env.
        return (env_settings, dotenv_settings, init_settings, file_secret_settings)


def _load_json_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


@lru_cache(maxsize=1)
def load_settings(config_path: Optional[str] = None) -> DarwinSettings:
    """Load and cache Darwin settings.

    Looks up the JSON config at (in order):
      - the ``config_path`` argument
      - the ``DARWIN_CONFIG`` environment variable
      - ``<project_root>/config/agent_config.json``
    """
    path_str = (
        config_path
        or os.environ.get("DARWIN_CONFIG")
        or str(PROJECT_ROOT / "config" / "agent_config.json")
    )
    json_fields = _load_json_config(Path(path_str))
    return DarwinSettings(**json_fields)


def clear_settings_cache() -> None:
    """Drop the cached settings instance; useful in tests."""
    load_settings.cache_clear()
