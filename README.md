# translate-bot

Mirrors the last 100 text messages of the [NEXA 🇨🇳 中文](https://t.me/Nexa_China) Telegram group
into English and publishes them as a static website, together with:

- a per-message **English translation** (with translator's notes for slang and crypto jargon),
- a per-message **sentiment** label and score (−1 … +1),
- an overall **summary**, the main **topics** being discussed (click a topic to filter the messages),
- the **mood** of the chat (label, score, description) and a sentiment distribution.

Everything is rendered into `site/index.html` (self-contained, light/dark aware) plus `site/data.json`.

## How it works

```
translate-bot fetch    Telethon (MTProto)  ->  data/messages.json     last 100 text messages
translate-bot analyze  Claude (claude-opus-5) ->  data/report.json    translation + sentiment + summary
translate-bot build    Jinja2              ->  site/index.html       static site
translate-bot run      all three in sequence
```

`Nexa_China` is a *group*, not a broadcast channel, so its history is not available through the
public `t.me/s/...` preview or the Bot API. The fetch step therefore uses Telethon with a normal
Telegram user account (yours), which can read any public group.

Translation runs in batches of 25 with the whole 100-message transcript supplied as cached context,
so short replies are translated with their surrounding conversation in view. The analysis is
returned as validated JSON via structured outputs; the schemas live in `translate_bot/models.py`.
Server-side refusal fallbacks are enabled (`fallbacks="default"`), so a rare safety decline on the
main model is retried automatically on a fallback model inside the same request.

## Setup

1. Install [uv](https://docs.astral.sh/uv/) and run `uv sync`.
2. Create a Telegram application at <https://my.telegram.org/apps> to get an **API ID** and **API hash**.
3. Get an Anthropic API key from <https://console.anthropic.com/settings/keys>.
4. `cp .env.example .env` and fill in `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `ANTHROPIC_API_KEY`.

## Run

```bash
uv run translate-bot run      # first run asks for your phone number + login code (once)
uv run translate-bot serve    # http://127.0.0.1:8000/
```

The Telegram login is cached in `data/telegram.session` (git-ignored). Re-run `translate-bot run`
whenever you want the site refreshed; `translate-bot build` alone re-renders without spending API credits.

Useful overrides in `.env`: `TELEGRAM_CHAT` (another public group), `MESSAGE_LIMIT`, `ANTHROPIC_MODEL`.

## Publishing

`site/` is plain static files — drop it on any host (GitHub Pages, Netlify, Cloudflare Pages, S3, nginx).

A GitHub Actions workflow (`.github/workflows/publish.yml`) is included that rebuilds and deploys to
GitHub Pages every 6 hours (and on demand). Because CI cannot do the interactive Telegram login, it
uses a string session instead:

```bash
uv run translate-bot login    # logs in once and prints a TELEGRAM_SESSION string
```

Then in the repository settings:

- **Settings → Pages → Source: GitHub Actions**
- **Settings → Secrets → Actions**: add `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION`, `ANTHROPIC_API_KEY`

The session string grants access to your Telegram account — treat it like a password.

## Cost

Each run makes 4 translation requests (sharing one cached prefix) plus 1 summary request against
`claude-opus-5`; a 100-message window is on the order of a few US cents per run at current pricing.
