# Torrent Server (Phase 2: Security Baseline)

Private torrent queue + delivery server controlled via Telegram bot.

This repository is currently in **Phase 2** of the implementation plan: security baseline controls are in place, while core queue/status/delivery flows remain incremental.

## Implemented in Phase 2

- Environment-driven runtime configuration validation.
- qBittorrent client wrapper based on `qbittorrent-api`.
- Telegram runtime allowlist enforcement middleware for bot handlers.
- HMAC-signed expiring download token utilities and verification.
- Download-route skeleton that enforces token validity.
- Docker Compose setup for bot service + internal qBittorrent service.

## Security baseline behavior

- qBittorrent Web UI is **not published** on a host port in `docker-compose.yml`; it stays internal to the Compose network. Do not expose it directly to the public internet.
- Secrets (bot token, qBittorrent credentials, token signing secret) are loaded from `.env`.
- Telegram allowlist is configured with `TELEGRAM_ALLOWED_USER_IDS` and enforced at runtime.
- Download links are tokenized and expiring.

### Telegram allowlist enforcement

- Incoming bot events are checked against `TELEGRAM_ALLOWED_USER_IDS`.
- If a user is not allowlisted, the bot returns:
  - `Unauthorized: this bot is restricted to approved users.`
- Unauthorized users are blocked before handlers execute.

### Expiring download token behavior

- Token format: `base64url(payload).base64url(signature)`.
- Payload fields:
  - `ref` (torrent/file path reference)
  - `exp` (UNIX expiry timestamp)
- Signature algorithm: HMAC-SHA256 using `DOWNLOAD_TOKEN_SECRET`.
- Verification outcome:
  - invalid/tampered token → `403`
  - expired token → `410`
- Default token TTL is controlled by `DOWNLOAD_TOKEN_TTL_SECONDS` (default `3600`).

### Secret rotation note

- Rotating `DOWNLOAD_TOKEN_SECRET` invalidates active download links signed with the previous secret.
- Rotate during a maintenance window if preserving currently issued links is required.

## Secret handling policy

- `.env.example` is committed as a template with placeholders only.
- Real secrets belong in local `.env` (or your secret manager in production) and must never be committed.

## Configuration

1. Copy `.env.example` to `.env`.
2. Fill in required values:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_ALLOWED_USER_IDS`
   - `QBITTORRENT_USERNAME` and `QBITTORRENT_PASSWORD`
   - `QBITTORRENT_TZ` (defaults to `Europe/Berlin`)
   - `DOWNLOAD_TOKEN_SECRET`
   - `DOWNLOAD_BASE_URL`
   - `DOWNLOAD_TOKEN_TTL_SECONDS`

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

## Verification commands

```bash
docker compose config
pytest -q
ruff check .
```

## Next (Phase 3)

- Queue ingress (`/add`, optional torrent-file upload).
- Status tracking (`/status`, polling/sync workflow).
- Expiring link issuance for completed items.
- Retention/cleanup controls to prevent disk exhaustion.
