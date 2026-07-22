"""
Runtime configuration, loaded from environment variables (.env locally,
repo Secrets in GitHub Actions). This module is the ONLY place that reads
credentials - core logic in src/dealhunter/ receives a Settings instance
and never touches os.environ directly, so swapping the config source
(e.g. per-user config in a future multi-user version) doesn't require
touching matching/scoring/pipeline code.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Reddit
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "dealhunter/0.1"

    # eBay
    ebay_client_id: str = ""
    ebay_client_secret: str = ""

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"

    # ntfy.sh
    ntfy_server: str = "https://ntfy.sh"
    ntfy_topic: str = "dealhunter-changeme"

    # Paths
    dealhunter_data_dir: str = "data"
    dealhunter_config_dir: str = "config"

    @property
    def data_dir(self) -> Path:
        p = REPO_ROOT / self.dealhunter_data_dir
        p.mkdir(parents=True, exist_ok=True)
        (p / "state").mkdir(parents=True, exist_ok=True)
        return p

    @property
    def config_dir(self) -> Path:
        return REPO_ROOT / self.dealhunter_config_dir

    @property
    def watchlist_path(self) -> Path:
        return self.config_dir / "watchlist.yaml"

    @property
    def categories_path(self) -> Path:
        return self.config_dir / "categories.yaml"

    @property
    def findings_path(self) -> Path:
        return self.data_dir / "findings.json"

    @property
    def health_path(self) -> Path:
        return self.data_dir / "health.json"

    @property
    def state_dir(self) -> Path:
        return self.data_dir / "state"


def get_settings() -> Settings:
    return Settings()
