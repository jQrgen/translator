"""Pydantic models shared by the fetch, analyze and build steps.

The `*Analysis` / `ChatSummary` models double as the structured-output schemas
handed to Claude, so their field descriptions are part of the prompt.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ChatInfo(BaseModel):
    title: str
    username: str
    url: str
    member_count: int | None = None


class RawMessage(BaseModel):
    id: int
    date: datetime
    sender_id: int | None = None
    sender_name: str
    text: str
    reply_to_id: int | None = None
    link: str | None = None


class Sentiment(str, Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"
    mixed = "mixed"


class MessageAnalysis(BaseModel):
    id: int = Field(description="The id of the message being analysed, copied exactly from the input.")
    translation: str = Field(
        description="Faithful, natural English translation. Keep the register (casual chat, slang, "
        "sarcasm, emoji) and keep tickers/URLs/usernames as-is. Do not add commentary."
    )
    sentiment: Sentiment = Field(description="Overall emotional tone of this message.")
    sentiment_score: float = Field(
        ge=-1, le=1,
        description="Fine-grained tone from -1 (very negative/hostile) through 0 (neutral) to +1 (very positive/enthusiastic).",
    )
    note: str | None = Field(
        default=None,
        description="Optional one-line translator's note for slang, memes, wordplay or crypto jargon a "
        "non-Chinese reader would miss. Omit when nothing needs explaining.",
    )


class BatchAnalysis(BaseModel):
    messages: list[MessageAnalysis] = Field(description="One entry per input message, same order as the input.")


class Topic(BaseModel):
    title: str = Field(description="Short topic label, 2-6 words.")
    summary: str = Field(description="One or two sentences on what was said about it and by whom (use display names).")
    message_ids: list[int] = Field(description="Ids of the messages that belong to this topic.")
    sentiment: Sentiment = Field(description="Prevailing tone within this topic.")


class Highlight(BaseModel):
    message_id: int
    why: str = Field(description="Why this message stands out (funny, important announcement, heated moment, etc).")


class ChatSummary(BaseModel):
    headline: str = Field(description="One sentence, max ~20 words, capturing what this slice of the chat is about.")
    summary: str = Field(description="A short paragraph (3-6 sentences) summarising the conversation for someone who was not there.")
    topics: list[Topic] = Field(description="The 3-8 main topics, most-discussed first.")
    mood_label: str = Field(description="A 1-4 word label for the overall mood, e.g. 'Cautiously optimistic', 'Frustrated', 'Playful'.")
    mood_description: str = Field(description="2-4 sentences describing the mood, how it shifts over the window, and what drives it.")
    mood_score: float = Field(ge=-1, le=1, description="Overall mood from -1 (very negative) to +1 (very positive).")
    highlights: list[Highlight] = Field(description="2-5 messages worth reading first.")


class AnalyzedMessage(RawMessage):
    translation: str
    sentiment: Sentiment
    sentiment_score: float
    note: str | None = None


class Report(BaseModel):
    chat: ChatInfo
    generated_at: datetime
    model: str
    window_start: datetime
    window_end: datetime
    messages: list[AnalyzedMessage]
    summary: ChatSummary

    @property
    def sentiment_counts(self) -> dict[str, int]:
        counts = {s.value: 0 for s in Sentiment}
        for m in self.messages:
            counts[m.sentiment.value] += 1
        return counts
