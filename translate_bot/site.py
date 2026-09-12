"""Render the reports into a self-contained static site: an overview at / and one page per chat at /<slug>/."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import Settings
from .models import Report, Sentiment

TEMPLATES = Path(__file__).parent / "templates"

SENTIMENT_META = {
    Sentiment.positive: {"label": "Positive", "glyph": "+"},
    Sentiment.mixed: {"label": "Mixed", "glyph": "±"},
    Sentiment.neutral: {"label": "Neutral", "glyph": "·"},
    Sentiment.negative: {"label": "Negative", "glyph": "−"},
}
SENTIMENT_ORDER = (Sentiment.positive, Sentiment.mixed, Sentiment.neutral, Sentiment.negative)


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
    env.filters["iso"] = lambda dt: dt.isoformat()
    env.filters["utc"] = lambda dt: dt.strftime("%Y-%m-%d %H:%M UTC")
    return env


def _distribution(report: Report) -> list[dict]:
    counts = report.sentiment_counts
    total = max(len(report.messages), 1)
    return [
        {
            "key": s.value,
            "label": SENTIMENT_META[s]["label"],
            "glyph": SENTIMENT_META[s]["glyph"],
            "count": counts[s.value],
            "pct": round(100 * counts[s.value] / total, 1),
        }
        for s in SENTIMENT_ORDER
    ]


def _mood_pct(report: Report) -> float:
    return round((report.summary.mood_score + 1) / 2 * 100, 1)


def _nav(reports: list[Report]) -> list[dict]:
    return [{"slug": r.chat.slug, "title": r.chat.title, "language": r.chat.language, "flag": r.chat.flag} for r in reports]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_chat_page(env: Environment, settings: Settings, report: Report, nav: list[dict]) -> Path:
    by_id = {m.id: m for m in report.messages}
    topic_ids = {m.id: [] for m in report.messages}
    for idx, topic in enumerate(report.summary.topics):
        for mid in topic.message_ids:
            if mid in topic_ids:
                topic_ids[mid].append(idx)

    html = env.get_template("index.html.j2").render(
        report=report,
        summary=report.summary,
        messages=report.messages,
        by_id=by_id,
        topic_ids=topic_ids,
        topic_counts=[len([i for i in t.message_ids if i in by_id]) for t in report.summary.topics],
        distribution=_distribution(report),
        sentiment_meta={s.value: SENTIMENT_META[s] for s in Sentiment},
        mood_pct=_mood_pct(report),
        nav=nav,
        current=report.chat.slug,
        root="../",
    )
    out = settings.site_dir / report.chat.slug
    _write(out / "index.html", html)
    _write(out / "data.json", json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return out / "index.html"


def build_site(settings: Settings, reports: list[Report]) -> Path:
    """Render every chat page plus the overview. Files are overwritten in place so a running server stays consistent."""
    if not reports:
        raise RuntimeError("No reports to render.")
    env = _env()
    nav = _nav(reports)
    for report in reports:
        build_chat_page(env, settings, report, nav)

    overview = env.get_template("overview.html.j2").render(
        reports=reports,
        nav=nav,
        current="overview",
        root="./",
        limit=settings.message_limit,
        model=settings.model,
        generated_at=max(r.generated_at for r in reports).astimezone(timezone.utc),
        distribution={r.chat.slug: _distribution(r) for r in reports},
        mood_pct={r.chat.slug: _mood_pct(r) for r in reports},
    )
    _write(settings.site_dir / "index.html", overview)
    _write(settings.site_dir / ".nojekyll", "")
    return settings.site_dir / "index.html"
