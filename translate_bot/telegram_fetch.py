"""Pull the most recent text messages from a public Telegram group via MTProto."""
from __future__ import annotations

import asyncio
import sys
import webbrowser
from getpass import getpass

import qrcode
import qrcode.image.svg

from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from telethon.tl import types
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import User

from .config import ChatSpec, Settings
from .models import ChatInfo, RawMessage


def make_client(settings: Settings) -> TelegramClient:
    if settings.session_string:
        session = StringSession(settings.session_string)
    else:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        session = str(settings.session_path)
    return TelegramClient(session, settings.api_id, settings.api_hash)


_CODE_ROUTES = {
    types.auth.SentCodeTypeApp: "a message in the Telegram app on your other logged-in devices (look for the official 'Telegram' service chat)",
    types.auth.SentCodeTypeSms: "SMS",
    types.auth.SentCodeTypeCall: "a phone call that reads the code out",
    types.auth.SentCodeTypeFlashCall: "a flash call — the code is the last digits of the calling number",
    types.auth.SentCodeTypeMissedCall: "a missed call — the code is the last digits of the calling number",
    types.auth.SentCodeTypeEmailCode: "the login email configured in Telegram (Settings → Privacy and Security → Login Email)",
    types.auth.SentCodeTypeSetUpEmailRequired: "nowhere yet — Telegram requires this account to set up a login email in the app first",
    types.auth.SentCodeTypeFragmentSms: "Fragment (this is an anonymous number)",
}


def _describe(code_type) -> str:
    return _CODE_ROUTES.get(type(code_type), type(code_type).__name__)


def _show_qr(url: str, settings_dir) -> None:
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make()
    qr.print_ascii(invert=True)
    svg_path = settings_dir / "login_qr.svg"
    qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=12).save(str(svg_path))
    print(f"(If the terminal QR won't scan, the same code was saved to {svg_path} — open it and scan that.)", file=sys.stderr)
    webbrowser.open(svg_path.resolve().as_uri())


async def _finish_2fa(client: TelegramClient) -> None:
    while True:
        try:
            await client.sign_in(password=getpass("Two-step verification password: "))
            return
        except errors.PasswordHashInvalidError:
            print("Wrong password — try again.", file=sys.stderr)


async def _qr_login(client: TelegramClient, settings_dir) -> None:
    try:
        qr = await client.qr_login()
    except errors.SessionPasswordNeededError:
        # The session already passed the code/QR step earlier and only the 2FA password is missing.
        await _finish_2fa(client)
        return
    print("\nOn your phone: Telegram → Settings → Devices → Link Desktop Device, then scan this:\n", file=sys.stderr)
    while True:
        _show_qr(qr.url, settings_dir)
        try:
            await qr.wait(timeout=30)
            return
        except asyncio.TimeoutError:
            await qr.recreate()
            print("\nQR expired — here is a fresh one:\n", file=sys.stderr)
        except errors.SessionPasswordNeededError:
            await _finish_2fa(client)
            return


async def ensure_authorized(client: TelegramClient, settings_dir=None) -> None:
    """Interactive login: QR scan (default) or a phone number + login code."""
    await client.connect()
    if await client.is_user_authorized():
        return
    from pathlib import Path
    settings_dir = Path(settings_dir or ".")
    settings_dir.mkdir(parents=True, exist_ok=True)
    print("Log in to Telegram. Press Enter to scan a QR code with your phone (recommended — no login code needed),\n"
          "or type your phone number to receive a login code instead.", file=sys.stderr)
    phone = input("Phone number, or Enter for QR: ").strip()
    if not phone:
        await _qr_login(client, settings_dir)
        return
    try:
        sent = await client.send_code_request(phone)
    except errors.SessionPasswordNeededError:
        await _finish_2fa(client)
        return
    while True:
        print(f"Telegram sent the code via: {_describe(sent.type)}", file=sys.stderr)
        if sent.next_type:
            print(f"  If it doesn't arrive, type 'resend' to get it via: {_describe(sent.next_type)}", file=sys.stderr)
        code = input("Login code (or 'resend'): ").strip()
        if code.lower() == "resend":
            try:
                sent = await client.send_code_request(phone)  # Telethon issues ResendCode for a known phone
            except errors.FloodWaitError as e:
                raise SystemExit(f"Telegram asks you to wait {e.seconds} seconds before requesting another code.")
            except errors.SendCodeUnavailableError:
                print("Telegram has no other delivery route for this number — the code is in the Telegram app "
                      "on a device you're logged in to (official 'Telegram' chat; check Archived chats too).", file=sys.stderr)
            continue
        try:
            await client.sign_in(phone, code)
        except errors.SessionPasswordNeededError:
            await _finish_2fa(client)
        except (errors.PhoneCodeInvalidError, errors.PhoneCodeExpiredError, errors.PhoneCodeEmptyError):
            print("That code was not accepted — try again, or type 'resend'.", file=sys.stderr)
            continue
        return


def _display_name(sender) -> str:
    if isinstance(sender, User):
        name = " ".join(p for p in (sender.first_name, sender.last_name) if p).strip()
        return name or (f"@{sender.username}" if sender.username else f"user {sender.id}")
    title = getattr(sender, "title", None)
    return title or "unknown"


async def fetch_chat(client: TelegramClient, spec: ChatSpec, limit: int) -> tuple[ChatInfo, list[RawMessage]]:
    """Return chat metadata plus the last `limit` text messages of one group, oldest first."""
    entity = await client.get_entity(spec.username)
    full = await client(GetFullChannelRequest(entity))
    chat = ChatInfo(
        title=entity.title,
        username=entity.username or spec.username,
        url=f"https://t.me/{entity.username or spec.username}",
        language=spec.language,
        lang_code=spec.lang_code,
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
        if len(messages) >= limit:
            break

    messages.reverse()
    print(f"Fetched {len(messages)} text messages from {chat.title}", file=sys.stderr)
    return chat, messages


async def fetch_messages(
    settings: Settings, specs: list[ChatSpec] | None = None
) -> list[tuple[ChatSpec, ChatInfo, list[RawMessage]]]:
    """Fetch every configured chat over a single connection. A chat that errors is logged and skipped."""
    client = make_client(settings)
    await ensure_authorized(client, settings.data_dir)  # interactive on first run
    results: list[tuple[ChatSpec, ChatInfo, list[RawMessage]]] = []
    try:
        for spec in (specs or settings.chats):
            try:
                info, messages = await fetch_chat(client, spec, settings.message_limit)
                results.append((spec, info, messages))
            except Exception as e:
                print(f"[{spec.username}] fetch failed, skipping: {type(e).__name__}: {e}", file=sys.stderr)
    finally:
        await client.disconnect()
    return results


async def export_string_session(settings: Settings) -> str:
    """Log in interactively and return a StringSession for headless (CI) use."""
    client = TelegramClient(StringSession(), settings.api_id, settings.api_hash)
    await ensure_authorized(client, settings.data_dir)
    try:
        return client.session.save()
    finally:
        await client.disconnect()
