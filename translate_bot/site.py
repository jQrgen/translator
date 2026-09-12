"""Render the report into a self-contained static site."""
from __future__ import annotations

import json
import shutil
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


def build_site(settings: Settings, report: Report) -> Path:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]))
    env.filters["iso"] = lambda dt: dt.isoformat()
    env.filters["utc"] = lambda dt: dt.strftime("%Y-%m-%d %H:%M UTC")

    by_id = {m.id: m for m in report.messages}
    topic_ids = {m.id: [] for m in report.messages}
    for idx, topic in enumerate(report.summary.topics):
        for mid in topic.message_ids:
            if mid in topic_ids:
                topic_ids[mid].append(idx)

    counts = report.sentiment_counts
    total = max(len(report.messages), 1)
    distribution = [
        {
            "key": s.value,
            "label": SENTIMENT_META[s]["label"],
            "glyph": SENTIMENT_META[s]["glyph"],
            "count": counts[s.value],
            "pct": round(100 * counts[s.value] / total, 1),
        }
        for s in (Sentiment.positive, Sentiment.mixed, Sentiment.neutral, Sentiment.negative)
    ]

    html = env.get_template("index.html.j2").render(
        report=report,
        summary=report.summary,
        messages=report.messages,
        by_id=by_id,
        topic_ids=topic_ids,
        topic_counts=[len([i for i in t.message_ids if i in by_id]) for t in report.summary.topics],
        distribution=distribution,
        sentiment_meta={s.value: SENTIMENT_META[s] for s in Sentiment},
        mood_pct=round((report.summary.mood_score + 1) / 2 * 100, 1),
    )

    out = settings.site_dir
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / "data.json").write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / ".nojekyll").write_text("")
    return out / "index.html"
