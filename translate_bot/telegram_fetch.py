"""Pull the most recent text messages from a public Telegram group via MTProto."""
from __future__ import annotations

import sys

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import User

from .config import Settings
from .models import ChatInfo, RawMessage


def make_client(settings: Settings) -> TelegramClient:
    if settings.session_string:
        session = StringSession(settings.session_string)
    else:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        session = str(settings.session_path)
    return TelegramClient(session, settings.api_id, settings.api_hash)


def _display_name(sender) -> str:
    if isinstance(sender, User):
        name = " ".join(p for p in (sender.first_name, sender.last_name) if p).strip()
        return name or (f"@{sender.username}" if sender.username else f"user {sender.id}")
    title = getattr(sender, "title", None)
    return title or "unknown"


async def fetch_messages(settings: Settings) -> tuple[ChatInfo, list[RawMessage]]:
    """Return chat metadata plus the last `message_limit` text messages, oldest first."""
    async with make_client(settings) as client:  # prompts for phone/code on first run
        entity = await client.get_entity(settings.chat)
        full = await client(GetFullChannelRequest(entity))
        chat = ChatInfo(
            title=entity.title,
            username=entity.username or settings.chat,
            url=f"https://t.me/{entity.username or settings.chat}",
            member_count=getattr(full.full_chat, "participants_count", None),
        )

        messages: list[RawMessage] = []
        names: dict[int, str] = {}
        async for msg in client.iter_messages(entity):
            text = (msg.message or "").strip()
            if not text:
                continue  # service messages, stickers, media without caption
            sender_id = msg.sender_id
            if sender_id is not None and sender_id not in names:
                names[sender_id] = _display_name(await msg.get_sender())
            messages.append(
                RawMessage(
                    id=msg.id,
                    date=msg.date,
                    sender_id=sender_id,
                    sender_name=names.get(sender_id, "unknown"),
                    text=text,
                    reply_to_id=msg.reply_to.reply_to_msg_id if msg.reply_to else None,
                    link=f"{chat.url}/{msg.id}",
                )
            )
            if len(messages) >= settings.message_limit:
                break

    messages.reverse()
    print(f"Fetched {len(messages)} text messages from {chat.title}", file=sys.stderr)
    return chat, messages


async def export_string_session(settings: Settings) -> str:
    """Log in interactively and return a StringSession for headless (CI) use."""
    async with TelegramClient(StringSession(), settings.api_id, settings.api_hash) as client:
        return client.session.save()
