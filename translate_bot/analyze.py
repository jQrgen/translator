"""Translate, score sentiment, and summarise a window of chat messages with Claude."""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone

import anthropic

from .config import Settings
from .models import (
    AnalyzedMessage,
    BatchAnalysis,
    ChatInfo,
    ChatSummary,
    RawMessage,
    Report,
)

BATCH_SIZE = 25
MAX_CONCURRENCY = 4
FALLBACK_BETA = "server-side-fallback-2026-07-01"

TRANSLATE_SYSTEM = """You are a professional Chinese-to-English translator and community analyst.

You are working on the public Telegram group of Nexa (nexa.org), a proof-of-work cryptocurrency. The group is its official Chinese-language community, so expect crypto jargon (币, 矿, 算力, 交易所, 上所, 拉盘, 砸盘, 韭菜, 梭哈, 空投…), internet slang, sarcasm, and very short replies whose meaning depends on the messages around them.

You will receive the full recent transcript in chronological order for context, followed by the subset of message ids you must process in this call.

For every requested id:
- Translate faithfully into natural English, at the same register as the original (casual stays casual, rude stays rude, jokes stay jokes). Keep emoji, tickers, URLs, @usernames and numbers unchanged. Never soften, expand, or editorialise.
- Classify sentiment (positive / neutral / negative / mixed) and give a score from -1 to 1. Judge the tone the sender is expressing, not how the reader would feel about the news. Pure information, questions, and greetings are neutral (score near 0).
- Add a short note only when a non-Chinese reader would otherwise miss slang, a meme, wordplay, or a cultural reference.

Process every requested id exactly once, in the given order, and copy ids exactly."""

SUMMARY_SYSTEM = """You are a community analyst writing an English briefing about the official Chinese-language Telegram group of Nexa (nexa.org), a proof-of-work cryptocurrency.

You will receive a window of recent messages (original Chinese, English translation, sender display name, timestamp, per-message sentiment). Write for an English-speaking team member who does not read Chinese and was not in the chat.

Guidelines:
- Identify the main topics actually discussed, most-discussed first, and attribute them to the participants by display name. Assign each message to at most one topic; small talk that fits nowhere can be left out.
- Describe the mood honestly: what people are excited, worried, annoyed or amused about, and whether the tone shifts across the window. Ground every claim in the messages; do not speculate beyond them.
- Pick a few highlights worth reading first.
- Be concrete and concise. No marketing language."""


def _transcript_line(m: RawMessage) -> dict:
    line = {
        "id": m.id,
        "time": m.date.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "sender": m.sender_name,
        "text": m.text,
    }
    if m.reply_to_id is not None:
        line["reply_to"] = m.reply_to_id
    return line


def _check_stop(response, what: str) -> None:
    if response.stop_reason == "refusal":
        details = response.stop_details
        reason = f"{details.category}: {details.explanation}" if details else "no details"
        raise RuntimeError(f"Claude declined the {what} request ({reason}).")
    if response.stop_reason == "max_tokens":
        raise RuntimeError(f"The {what} response was cut off by max_tokens; lower BATCH_SIZE or raise max_tokens.")


async def _translate_batch(
    client: anthropic.AsyncAnthropic,
    settings: Settings,
    transcript_json: str,
    batch: list[RawMessage],
    sem: asyncio.Semaphore,
    attempt: int = 1,
) -> dict[int, AnalyzedMessage]:
    ids = [m.id for m in batch]
    async with sem:
        response = await client.beta.messages.parse(
            model=settings.model,
            max_tokens=16000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            system=[{"type": "text", "text": TRANSLATE_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Full transcript (JSON, chronological):\n" + transcript_json,
                            "cache_control": {"type": "ephemeral"},
                        },
                        {
                            "type": "text",
                            "text": "Process these message ids, in this order: " + json.dumps(ids),
                        },
                    ],
                }
            ],
            output_format=BatchAnalysis,
        )
    _check_stop(response, "translation")
    parsed = response.parsed_output
    if parsed is None:
        raise RuntimeError("Translation response contained no parseable output.")

    by_id = {m.id: m for m in batch}
    done: dict[int, AnalyzedMessage] = {}
    for a in parsed.messages:
        raw = by_id.get(a.id)
        if raw is None or a.id in done:
            continue
        done[a.id] = AnalyzedMessage(
            **raw.model_dump(),
            translation=a.translation,
            sentiment=a.sentiment,
            sentiment_score=a.sentiment_score,
            note=a.note or None,
        )

    missing = [m for m in batch if m.id not in done]
    if missing:
        if attempt >= 3:
            raise RuntimeError(f"Claude skipped message ids {[m.id for m in missing]} after {attempt} attempts.")
        print(f"  retrying {len(missing)} skipped message(s)…", file=sys.stderr)
        done.update(await _translate_batch(client, settings, transcript_json, missing, sem, attempt + 1))
    return done


async def translate_all(
    client: anthropic.AsyncAnthropic, settings: Settings, messages: list[RawMessage]
) -> list[AnalyzedMessage]:
    transcript_json = json.dumps([_transcript_line(m) for m in messages], ensure_ascii=False, indent=0)
    batches = [messages[i : i + BATCH_SIZE] for i in range(0, len(messages), BATCH_SIZE)]
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    print(f"Translating {len(messages)} messages in {len(batches)} batch(es) with {settings.model}…", file=sys.stderr)
    results = await asyncio.gather(*(_translate_batch(client, settings, transcript_json, b, sem) for b in batches))
    merged: dict[int, AnalyzedMessage] = {}
    for r in results:
        merged.update(r)
    return [merged[m.id] for m in messages]


async def summarize(
    client: anthropic.AsyncAnthropic, settings: Settings, chat: ChatInfo, messages: list[AnalyzedMessage]
) -> ChatSummary:
    rows = [
        {
            "id": m.id,
            "time": m.date.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "sender": m.sender_name,
            "zh": m.text,
            "en": m.translation,
            "sentiment": m.sentiment.value,
            **({"reply_to": m.reply_to_id} if m.reply_to_id is not None else {}),
        }
        for m in messages
    ]
    print("Summarising topics and mood…", file=sys.stderr)
    response = await client.beta.messages.parse(
        model=settings.model,
        max_tokens=16000,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        system=SUMMARY_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": f"Group: {chat.title} ({chat.url}), {len(messages)} messages.\n\n"
                + json.dumps(rows, ensure_ascii=False, indent=0),
            }
        ],
        output_format=ChatSummary,
    )
    _check_stop(response, "summary")
    if response.parsed_output is None:
        raise RuntimeError("Summary response contained no parseable output.")
    return response.parsed_output


async def build_report(settings: Settings, chat: ChatInfo, messages: list[RawMessage]) -> Report:
    if not messages:
        raise RuntimeError("No messages to analyse.")
    client = anthropic.AsyncAnthropic()
    analyzed = await translate_all(client, settings, messages)
    summary = await summarize(client, settings, chat, analyzed)
    known = {m.id for m in analyzed}
    for topic in summary.topics:  # drop any ids the model invented
        topic.message_ids = [i for i in topic.message_ids if i in known]
    summary.highlights = [h for h in summary.highlights if h.message_id in known]
    return Report(
        chat=chat,
        generated_at=datetime.now(timezone.utc),
        model=settings.model,
        window_start=messages[0].date,
        window_end=messages[-1].date,
        messages=analyzed,
        summary=summary,
    )
