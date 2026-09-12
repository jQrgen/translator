"""Command-line entry point.

    translate-bot run        fetch + analyze + build for every configured chat
    translate-bot fetch      pull the last N text messages of each chat into data/<chat>/messages.json
    translate-bot analyze    translate/score/summarise data/<chat>/messages.json -> data/<chat>/report.json
    translate-bot build      render data/*/report.json -> site/ (overview at /, one page per chat at /<chat>/)
    translate-bot refresh    one pass: fetch every chat and re-translate only those that changed, then rebuild
    translate-bot serve      serve site/ locally
    translate-bot watch      re-run the pipeline every N minutes and serve site/ (the "bot" mode)
    translate-bot login      print a Telegram StringSession for headless use

Chats come from CHATS in .env, e.g. CHATS=Nexa_China:Chinese,nexatr:Turkish
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import time
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import ChatSpec, ConfigError, Settings
from .models import ChatInfo, RawMessage, Report


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def _write_json(path: Path, model_or_dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = model_or_dict if isinstance(model_or_dict, dict) else model_or_dict.model_dump(mode="json")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _save_messages(settings: Settings, chat: ChatSpec, info: ChatInfo, messages: list[RawMessage]) -> None:
    _write_json(
        settings.messages_path(chat),
        {"chat": info.model_dump(mode="json"), "messages": [m.model_dump(mode="json") for m in messages]},
    )


def _load_messages(settings: Settings, chat: ChatSpec) -> tuple[ChatInfo, list[RawMessage]]:
    path = settings.messages_path(chat)
    if not path.exists():
        raise SystemExit(f"{path} not found — run `translate-bot fetch` first.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ChatInfo.model_validate(payload["chat"]), [RawMessage.model_validate(m) for m in payload["messages"]]


def _load_report(settings: Settings, chat: ChatSpec) -> Report | None:
    path = settings.report_path(chat)
    if not path.exists():
        return None
    try:
        return Report.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as e:
        _log(f"[{chat.username}] ignoring unreadable {path}: {e}")
        return None


def _load_reports(settings: Settings) -> list[Report]:
    reports = []
    for chat in settings.chats:
        report = _load_report(settings, chat)
        if report is None:
            _log(f"[{chat.username}] no report yet — run `translate-bot run` to create it")
        else:
            reports.append(report)
    return reports


def cmd_fetch(settings: Settings) -> None:
    from .telegram_fetch import fetch_messages

    for chat, info, messages in asyncio.run(fetch_messages(settings)):
        _save_messages(settings, chat, info, messages)
        _log(f"[{chat.username}] wrote {settings.messages_path(chat)}")


def cmd_analyze(settings: Settings) -> None:
    from .analyze import build_report

    for chat in settings.chats:
        info, messages = _load_messages(settings, chat)
        report = asyncio.run(build_report(settings, info, messages))
        _write_json(settings.report_path(chat), report)
        _log(f"[{chat.username}] wrote {settings.report_path(chat)}")


def cmd_build(settings: Settings) -> None:
    from .site import build_site

    reports = _load_reports(settings)
    if not reports:
        raise SystemExit("Nothing to render — no data/<chat>/report.json found.")
    _log(f"wrote {build_site(settings, reports)}")


def cmd_run(settings: Settings) -> None:
    cmd_fetch(settings)
    cmd_analyze(settings)
    cmd_build(settings)


def cmd_refresh(settings: Settings) -> None:
    """A single watch pass: re-translate only changed chats. Ideal for a scheduled CI job."""
    if not refresh(settings) and not (settings.site_dir / "index.html").exists():
        cmd_build(settings)


def refresh(settings: Settings) -> bool:
    """One pass over all chats: fetch, translate only the chats whose window changed, rebuild if any did."""
    from .analyze import build_report
    from .site import build_site
    from .telegram_fetch import fetch_messages

    changed = False
    for chat, info, messages in asyncio.run(fetch_messages(settings)):
        _save_messages(settings, chat, info, messages)
        previous = _load_report(settings, chat)
        if previous is not None and [m.id for m in messages] == [m.id for m in previous.messages]:
            _log(f"[{chat.username}] no new messages — skipping translation")
            continue
        try:
            report = asyncio.run(build_report(settings, info, messages))
        except Exception as e:  # one chat failing must not block the others
            _log(f"[{chat.username}] analysis failed: {type(e).__name__}: {e}")
            continue
        _write_json(settings.report_path(chat), report)
        _log(f"[{chat.username}] translated {len(messages)} messages, latest {messages[-1].date:%Y-%m-%d %H:%M} UTC")
        changed = True

    if changed:
        build_site(settings, _load_reports(settings))
        _log("site rebuilt")
    return changed


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # keep the watch log readable
        pass


def _make_server(settings: Settings, host: str, port: int) -> ThreadingHTTPServer:
    settings.site_dir.mkdir(parents=True, exist_ok=True)
    handler = partial(_QuietHandler, directory=str(settings.site_dir))
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"Serving {settings.site_dir} at http://{host}:{port}/", file=sys.stderr)
    return httpd


def cmd_serve(settings: Settings, host: str, port: int) -> None:
    if not (settings.site_dir / "index.html").exists():
        raise SystemExit("site/index.html not found — run `translate-bot build` first.")
    with _make_server(settings, host, port) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


def cmd_watch(settings: Settings, host: str, port: int, every_minutes: float) -> None:
    httpd = _make_server(settings, host, port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    if not (settings.site_dir / "index.html").exists() and _load_reports(settings):
        from .site import build_site

        build_site(settings, _load_reports(settings))
    interval = every_minutes * 60
    _log(f"Watching {', '.join(c.username for c in settings.chats)} every {every_minutes:g} min (Ctrl-C to stop).")
    try:
        while True:
            started = time.monotonic()
            try:
                refresh(settings)
            except KeyboardInterrupt:
                raise
            except Exception as e:  # keep the loop alive; the previous site stays served
                _log(f"pass failed: {type(e).__name__}: {e}")
            time.sleep(max(0.0, interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        _log("Stopping.")
    finally:
        httpd.shutdown()


def cmd_login(settings: Settings) -> None:
    from .telegram_fetch import export_string_session

    session = asyncio.run(export_string_session(settings))
    print("\nAdd this to your .env or CI secrets as TELEGRAM_SESSION (keep it private — it grants access to your account):\n", file=sys.stderr)
    print(session)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="translate-bot", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "fetch", "analyze", "build", "refresh", "login"):
        sub.add_parser(name)
    for name in ("serve", "watch"):
        sp = sub.add_parser(name)
        sp.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to expose on the network")
        sp.add_argument("--port", type=int, default=8000)
        if name == "watch":
            sp.add_argument("--every", type=float, default=60, metavar="MINUTES", help="minutes between passes (default 60)")
    args = parser.parse_args(argv)

    try:
        settings = Settings()
        if args.command == "serve":
            cmd_serve(settings, args.host, args.port)
        elif args.command == "watch":
            cmd_watch(settings, args.host, args.port, args.every)
        else:
            {"run": cmd_run, "fetch": cmd_fetch, "analyze": cmd_analyze, "build": cmd_build,
             "refresh": cmd_refresh, "login": cmd_login}[args.command](settings)
    except ConfigError as e:
        raise SystemExit(f"error: {e}")


if __name__ == "__main__":
    main()
