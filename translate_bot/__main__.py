"""Command-line entry point.

    translate-bot run        fetch + analyze + build (the normal path)
    translate-bot fetch      pull the last N text messages into data/messages.json
    translate-bot analyze    translate/score/summarise data/messages.json -> data/report.json
    translate-bot build      render data/report.json -> site/index.html
    translate-bot serve      serve site/ locally
    translate-bot login      print a Telegram StringSession for headless use
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from .config import ConfigError, Settings
from .models import ChatInfo, RawMessage, Report


def _read_messages(settings: Settings) -> tuple[ChatInfo, list[RawMessage]]:
    if not settings.messages_path.exists():
        raise SystemExit(f"{settings.messages_path} not found — run `translate-bot fetch` first.")
    payload = json.loads(settings.messages_path.read_text(encoding="utf-8"))
    return ChatInfo.model_validate(payload["chat"]), [RawMessage.model_validate(m) for m in payload["messages"]]


def _write_json(path, model_or_dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = model_or_dict if isinstance(model_or_dict, dict) else model_or_dict.model_dump(mode="json")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_fetch(settings: Settings) -> None:
    from .telegram_fetch import fetch_messages

    chat, messages = asyncio.run(fetch_messages(settings))
    _write_json(settings.messages_path, {"chat": chat.model_dump(mode="json"), "messages": [m.model_dump(mode="json") for m in messages]})
    print(f"Wrote {settings.messages_path}", file=sys.stderr)


def cmd_analyze(settings: Settings) -> None:
    from .analyze import build_report

    chat, messages = _read_messages(settings)
    report = asyncio.run(build_report(settings, chat, messages))
    _write_json(settings.report_path, report)
    print(f"Wrote {settings.report_path}", file=sys.stderr)


def cmd_build(settings: Settings) -> None:
    from .site import build_site

    if not settings.report_path.exists():
        raise SystemExit(f"{settings.report_path} not found — run `translate-bot analyze` first.")
    report = Report.model_validate_json(settings.report_path.read_text(encoding="utf-8"))
    out = build_site(settings, report)
    print(f"Wrote {out}", file=sys.stderr)


def cmd_run(settings: Settings) -> None:
    cmd_fetch(settings)
    cmd_analyze(settings)
    cmd_build(settings)


def cmd_serve(settings: Settings, port: int) -> None:
    if not (settings.site_dir / "index.html").exists():
        raise SystemExit("site/index.html not found — run `translate-bot build` first.")
    handler = partial(SimpleHTTPRequestHandler, directory=str(settings.site_dir))
    with ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        print(f"Serving {settings.site_dir} at http://127.0.0.1:{port}/ (Ctrl-C to stop)", file=sys.stderr)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


def cmd_login(settings: Settings) -> None:
    from .telegram_fetch import export_string_session

    session = asyncio.run(export_string_session(settings))
    print("\nAdd this to your .env or CI secrets as TELEGRAM_SESSION (keep it private — it grants access to your account):\n", file=sys.stderr)
    print(session)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="translate-bot", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "fetch", "analyze", "build", "login"):
        sub.add_parser(name)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    settings = Settings()
    try:
        if args.command == "serve":
            cmd_serve(settings, args.port)
        else:
            {"run": cmd_run, "fetch": cmd_fetch, "analyze": cmd_analyze, "build": cmd_build, "login": cmd_login}[args.command](settings)
    except ConfigError as e:
        raise SystemExit(f"error: {e}")


if __name__ == "__main__":
    main()
