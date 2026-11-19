"""Environment-derived settings. Secrets and local paths only — everything else
is a CLI argument."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Three levels up from this file: src/larklab/config.py -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"


@dataclass(frozen=True)
class Config:
    credentials_path: str
    token_path: str
    slack_bot_token: str = field(repr=False)  # keep the secret out of logs
    db_path: str
    crawl_progress_path: str  # how far each source has been read
    outbox_path: str  # recommendations Slack refused


def load_config() -> Config:
    """Load credentials and paths from .env."""
    load_dotenv(PROJECT_ROOT / ".env")
    return Config(
        credentials_path=_resolve_project_path(
            "GMAIL_CREDENTIALS_PATH", "credentials/credentials.json"
        ),
        token_path=_resolve_project_path("GMAIL_TOKEN_PATH", "credentials/token.json"),
        slack_bot_token=os.getenv("SLACK_BOT_TOKEN", ""),
        db_path=str(DATA_DIR / "larklab.db"),
        crawl_progress_path=str(DATA_DIR / "crawl_progress.json"),
        outbox_path=str(DATA_DIR / "outbox.json"),
    )


def _resolve_project_path(env_var: str, default_relative: str) -> str:
    """Read a path from an env var; relative paths resolve against PROJECT_ROOT."""
    path = Path(os.getenv(env_var, default_relative))
    return str(path if path.is_absolute() else PROJECT_ROOT / path)
