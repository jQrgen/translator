from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SITE_DIR = ROOT / "site"

load_dotenv(ROOT / ".env")


class ConfigError(RuntimeError):
    pass


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"{name} is not set. Copy .env.example to .env and fill it in, "
            f"or export it in your shell."
        )
    return value


@dataclass
class Settings:
    chat: str = field(default_factory=lambda: os.environ.get("TELEGRAM_CHAT", "Nexa_China").lstrip("@"))
    message_limit: int = field(default_factory=lambda: int(os.environ.get("MESSAGE_LIMIT", "100")))
    model: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_MODEL", "claude-opus-5"))
    session_string: str | None = field(default_factory=lambda: os.environ.get("TELEGRAM_SESSION") or None)
    data_dir: Path = DATA_DIR
    site_dir: Path = SITE_DIR

    @property
    def api_id(self) -> int:
        return int(_require("TELEGRAM_API_ID"))

    @property
    def api_hash(self) -> str:
        return _require("TELEGRAM_API_HASH")

    @property
    def messages_path(self) -> Path:
        return self.data_dir / "messages.json"

    @property
    def report_path(self) -> Path:
        return self.data_dir / "report.json"

    @property
    def session_path(self) -> Path:
        return self.data_dir / "telegram.session"
