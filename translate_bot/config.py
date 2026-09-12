from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SITE_DIR = ROOT / "site"

load_dotenv(ROOT / ".env")

DEFAULT_CHATS = ",".join([
    "Nexa_China:Chinese",
    "Nexa_Netherlands:Dutch",
    "Nexa_Germany:German",
    "Nexa_India:Hindi",
    "Nexa_Korean:Korean",
    "Nexa_NOR:Norwegian",
    "Nexa_Philippines:Filipino",
    "Nexa_Poland:Polish",
    "Nexa_RU:Russian",
    "Nexa_Spanish:Spanish",
    "NexaTR:Turkish",
    "Nexa_VIET:Vietnamese",
])

# BCP-47 tags for the <html lang> / lang="" attributes of original text.
LANG_CODES = {
    "chinese": "zh-Hans", "dutch": "nl", "german": "de", "hindi": "hi", "korean": "ko",
    "norwegian": "nb", "filipino": "fil", "tagalog": "fil", "polish": "pl", "russian": "ru",
    "spanish": "es", "turkish": "tr", "vietnamese": "vi", "portuguese": "pt", "french": "fr",
    "japanese": "ja", "indonesian": "id", "arabic": "ar", "persian": "fa", "italian": "it",
}


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


@dataclass(frozen=True)
class ChatSpec:
    username: str   # public group username, no @
    language: str   # human name of the source language, e.g. "Chinese"

    @property
    def slug(self) -> str:
        return self.username.lower()

    @property
    def lang_code(self) -> str:
        return LANG_CODES.get(self.language.lower(), self.language[:2].lower())


def parse_chats(spec: str) -> list[ChatSpec]:
    """'Nexa_China:Chinese,nexatr:Turkish' -> [ChatSpec, ...]"""
    chats: list[ChatSpec] = []
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        username, _, language = item.partition(":")
        username = username.strip().lstrip("@")
        if not username or not language.strip():
            raise ConfigError(f"CHATS entry {item!r} must look like username:Language")
        chats.append(ChatSpec(username, language.strip()))
    if not chats:
        raise ConfigError("CHATS is empty")
    return chats


def _chats_from_env() -> list[ChatSpec]:
    if os.environ.get("CHATS", "").strip():
        return parse_chats(os.environ["CHATS"])
    if os.environ.get("TELEGRAM_CHAT", "").strip():  # legacy single-chat setting
        return [ChatSpec(os.environ["TELEGRAM_CHAT"].strip().lstrip("@"), "Chinese")]
    return parse_chats(DEFAULT_CHATS)


@dataclass
class Settings:
    chats: list[ChatSpec] = field(default_factory=_chats_from_env)
    message_limit: int = field(default_factory=lambda: int(os.environ.get("MESSAGE_LIMIT", "100")))
    model: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_MODEL", "claude-opus-5"))
    session_string: str | None = field(default_factory=lambda: os.environ.get("TELEGRAM_SESSION") or None)
    workspace_id: str | None = field(default_factory=lambda: os.environ.get("ANTHROPIC_WORKSPACE_ID") or None)
    data_dir: Path = DATA_DIR
    site_dir: Path = SITE_DIR

    @property
    def api_id(self) -> int:
        return int(_require("TELEGRAM_API_ID"))

    @property
    def api_hash(self) -> str:
        return _require("TELEGRAM_API_HASH")

    def messages_path(self, chat: ChatSpec) -> Path:
        return self.data_dir / chat.slug / "messages.json"

    def report_path(self, chat: ChatSpec) -> Path:
        return self.data_dir / chat.slug / "report.json"

    @property
    def session_path(self) -> Path:
        return self.data_dir / "telegram.session"
