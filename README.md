# Torrent Server (Phase 1 Scaffold)

Private torrent queue + delivery server controlled via Telegram bot.

## What is included in this phase

- Python application scaffold with focused packages (`app/bot`, `app/services`, `app/db`, `app/api`, `app/security`).
- Environment-driven runtime configuration validation.
- qBittorrent client wrapper based on `qbittorrent-api`.
- Docker Compose setup for bot service + internal qBittorrent service.
- Lightweight scaffold validation through linting and runtime checks (no maintained test suite yet).

## Security notes

- qBittorrent Web UI is **not published** on a host port in `docker-compose.yml`; it stays internal to the Compose network.
- Secrets (bot token, qBittorrent credentials, token signing secret) are loaded from `.env`.
- Telegram allowlist is configured via `TELEGRAM_ALLOWED_USER_IDS`.

## Secret handling policy

- `.env.example` is committed **on purpose** as a template with placeholder values only.
- Real secrets must go in local `.env` (or your secret manager in production) and are ignored by git.
- Never commit real bot tokens, qBittorrent passwords, or signing secrets.

## Current testing policy

- This repository currently does **not** maintain an automated test suite.
- Validation is currently done with linting plus manual runtime verification.
- We can add tests later when feature flows stabilize.

## Configuration

1. Copy `.env.example` to `.env`.
2. Fill in all secret values:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_ALLOWED_USER_IDS`
   - `QBITTORRENT_USERNAME` and `QBITTORRENT_PASSWORD`
   - `QBITTORRENT_TZ` (defaults to `Europe/Berlin`)
   - `DOWNLOAD_TOKEN_SECRET`
   - `DOWNLOAD_BASE_URL`

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
python -m app.main
```

## Docker Compose run

```bash
cp .env.example .env
# edit .env with real values
docker compose up --build -d
```

## Verify current scaffold

```bash
docker compose config
ruff check .
```

## Next implementation slice

- Add Telegram handlers for `/add` and `/status`.
- Persist queue state in SQLite repositories.
- Expose tokenized expiring download route.
