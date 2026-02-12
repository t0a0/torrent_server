# Torrent Server (Phase 1 Scaffold)

Private torrent queue + delivery server controlled via Telegram bot.

## What is included in this phase

- Python application scaffold with focused packages (`app/bot`, `app/services`, `app/db`, `app/api`, `app/security`).
- Environment-driven runtime configuration validation.
- qBittorrent client wrapper based on `qbittorrent-api`.
- Docker Compose setup for bot service + internal qBittorrent service.
- Security baseline implementation with allowlist checks and expiring signed token support.

## Security baseline implemented in this phase

- Telegram user allowlist middleware blocks unauthorized users before handlers run.
- Download access tokens are HMAC-signed and include expiration (`exp`) checks.
- qBittorrent remains internal-only in Docker Compose (no public host port mapping).

## Security notes

- qBittorrent Web UI is **not published** on a host port in `docker-compose.yml`; it stays internal to the Compose network.
- Secrets (bot token, qBittorrent credentials, token signing secret) are loaded from `.env`.
- Telegram allowlist is configured via `TELEGRAM_ALLOWED_USER_IDS`.

## Secret handling policy

- `.env.example` is committed **on purpose** as a template with placeholder values only.
- Real secrets must go in local `.env` (or your secret manager in production) and are ignored by git.
- Never commit real bot tokens, qBittorrent passwords, or signing secrets.

## Current testing policy

- The repository maintains focused tests for security-critical logic (allowlist and token validation).
- Expand coverage as queue/state/link delivery features are implemented.

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
pytest -q
ruff check .
```

## Next implementation slice

- Add Telegram handlers for `/add` and `/status`.
- Persist queue state in SQLite repositories.
- Expose tokenized expiring download route.
