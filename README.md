# translate-bot

Mirrors the recent chat of Nexa's regional Telegram groups into English and publishes them
as a static website. Each community gets its own page with:

- a per-message **English translation** (with translator's notes for slang and crypto jargon),
- a per-message **sentiment** label and score (−1 … +1), newest message first,
- an overall **summary**, the main **topics** (click a topic to filter the messages),
- the **mood** (label, score, description) and a sentiment distribution,

plus an **overview** page linking every community with its headline, mood and sentiment mix.

**Live site: <https://jQrgen.github.io/translator/>**

The site is generated into `site/` (self-contained HTML, light/dark aware) — an overview at `/`
and one page per group at `/<username>/`, each with a `data.json` alongside it.

## Communities

Configured in `CHATS` in `.env` as `username:SourceLanguage` pairs. Defaults:

| | Group | Language |
|---|---|---|
| 🇨🇳 | Nexa_China | Chinese |
| 🇳🇱 | Nexa_Netherlands | Dutch |
| 🇩🇪 | Nexa_Germany | German |
| 🇮🇳 | Nexa_India | Hindi |
| 🇰🇷 | Nexa_Korean | Korean |
| 🇳🇴 | Nexa_NOR | Norwegian |
| 🇵🇭 | Nexa_Philippines | Filipino |
| 🇵🇱 | Nexa_Poland | Polish |
| 🇷🇺 | Nexa_RU | Russian |
| 🇪🇸 | Nexa_Spanish | Spanish |
| 🇹🇷 | NexaTR | Turkish |
| 🇻🇳 | Nexa_VIET | Vietnamese |

Add, remove or relabel groups by editing `CHATS` — no code changes needed.

## How it works

```
translate-bot fetch    Telethon (MTProto)  ->  data/<chat>/messages.json   last 100 text messages per group
translate-bot analyze  Claude (claude-opus-5) ->  data/<chat>/report.json  translation + sentiment + summary
translate-bot build    Jinja2              ->  site/                       overview + one page per group
translate-bot run      all three in sequence, for every configured group
translate-bot watch    loop: re-run every 60 min (--every) and serve site/ — a group whose 100-message
                       window is unchanged is not re-translated, so idle hours cost nothing
```

These are Telegram *groups*, not broadcast channels, so their history isn't available through the
public `t.me/s/...` preview or the Bot API. Fetching uses Telethon with a normal Telegram user
account (yours), which can read any public group. A group that is private or fails to load is
logged and skipped; the others still publish.

Translation runs in batches of 25 with the whole 100-message transcript supplied as cached context,
so short replies are translated with their surrounding conversation in view. The analysis is
returned as validated JSON via structured outputs; the schemas live in `translate_bot/models.py`.
Server-side refusal fallbacks are enabled (`fallbacks="default"`).

## Setup

1. Install [uv](https://docs.astral.sh/uv/) and run `uv sync`.
2. Create a Telegram application at <https://my.telegram.org/apps> for an **API ID** and **API hash**.
3. Get an Anthropic API key from <https://platform.claude.com/> (Console → API Keys). Create the key
   inside a workspace, or set `ANTHROPIC_WORKSPACE_ID` if the key is org-level.
4. `cp .env.example .env` and fill in `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `ANTHROPIC_API_KEY`.

## Run

```bash
uv run translate-bot run      # first run logs you in to Telegram (QR scan or login code), once
uv run translate-bot serve    # http://127.0.0.1:8000/
uv run translate-bot watch    # keep it running: re-check every group hourly and serve the site
```

`watch --every 30 --host 0.0.0.0 --port 8080` changes the cadence and exposes it on the network.
The Telegram login (QR scan or code + 2FA) happens once and is cached in `data/telegram.session`
(git-ignored). `translate-bot build` alone re-renders without spending API credits.

## Publishing to GitHub Pages

The built `site/` is committed, and `.github/workflows/deploy.yml` publishes it to Pages on every
push that touches `site/` (and on demand) — no secrets, deploys in well under a minute. To refresh:
regenerate locally (`translate-bot run` or leave `watch` running), commit `site/`, and push.

In the repo: **Settings → Pages → Source: GitHub Actions**.

For hands-off refreshing, `.github/workflows/refresh.yml` runs the whole pipeline hourly in CI and
deploys. CI can't do the interactive Telegram login, so it uses a string session:

```bash
uv run translate-bot login    # logs in once and prints a TELEGRAM_SESSION string
```

Then add repository secrets (**Settings → Secrets and variables → Actions**): `TELEGRAM_API_ID`,
`TELEGRAM_API_HASH`, `TELEGRAM_SESSION`, `ANTHROPIC_API_KEY` (and `ANTHROPIC_WORKSPACE_ID` if needed).
The session string grants access to your Telegram account — treat it like a password.

## Cost

Each group per run makes 4 translation requests (sharing one cached prefix) plus 1 summary request
against `claude-opus-5` — on the order of a few US cents per group. `watch` only spends when a
group's messages actually changed.
