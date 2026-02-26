# Torrent Server + Telegram Bot

This project runs a Telegram bot that can queue torrents in qBittorrent, track progress, and provide download links for completed files via an HTTP file server.

## Prerequisite

- **Docker + Docker Compose must be installed**.

> This README assumes you run everything with `docker compose`.

## Quick start

1. **Clone the repository** and enter it.
2. **Create your runtime env file**:

   ```bash
   cp .env.example .env
   ```

3. **Fill in `.env`** (see [Environment variables](#environment-variables)).
4. **Create required bind-mount directories**:

   ```bash
   mkdir -p \
     volumes/downloads \
     volumes/auth \
     volumes/qbittorrent_config \
     volumes/nginxproxymanager/data \
     volumes/nginxproxymanager/letsencrypt
   ```

5. **Start services**:

   ```bash
   docker compose up -d --build
   ```

6. **Handle first qBittorrent login/password initialization** (important):
   - On first launch, qBittorrent logs a **temporary admin password**.
   - Read it with:

     ```bash
     docker compose logs qbittorrent | rg -i "temporary password|admin password|password"
     ```

   - Open qBittorrent Web UI (`http://localhost:8080`) and sign in with the temporary password.
   - Change username/password in qBittorrent Web UI to match your `.env` values:
     - `QBITTORRENT_USERNAME`
     - `QBITTORRENT_PASSWORD`

7. **Restart containers after changing qBittorrent credentials**:
   - Recommended because the bot initializes its torrent service on startup and may attempt login before qBittorrent has fully persisted updated credentials.

   ```bash
   docker compose down
   docker compose up -d
   ```

## Environment variables

Rename `.env.example` to `.env` and fill all values.

| Variable | Required | What it is for |
|---|---:|---|
| `TELEGRAM_BOT_TOKEN` | Yes | Telegram Bot API token from BotFather. |
| `BOT_OWNER_USER_ID` | Yes | Telegram `user_id` of the bot owner/admin (allowed to run admin-only commands). |
| `QBITTORRENT_URL` | Yes | qBittorrent Web UI/API URL used by the bot (for Docker Compose default: `http://qbittorrent:8080`). |
| `QBITTORRENT_USERNAME` | Yes | qBittorrent Web UI username used by the bot API client. |
| `QBITTORRENT_PASSWORD` | Yes | qBittorrent Web UI password used by the bot API client. |
| `TORRENT_INPUT_TMP_DIR` | Yes | Temp folder inside the bot container for uploaded `.torrent` files before queueing. |
| `AUTH_DB_PATH` | Yes | SQLite file path for whitelist/auth data (default compose path: `/auth/auth.db`). |
| `ACTIVE_DOWNLOADS_ROOT` | Yes | Path where in-progress torrent data is stored. |
| `FINISHED_DOWNLOADS_ROOT` | Yes | Path where completed downloads are stored (served by file server). |
| `DOWNLOAD_RECORDS_DB_PATH` | Yes | SQLite path used to track download records/metadata. |
| `FINISHED_DOWNLOAD_RETENTION_DAYS` | Yes | Retention period for completed downloads/records. |
| `HFS_BASE_URL` | Yes | **Base URL for the file server** used when generating user download links. |
| `DOWNLOAD_LINK_SECRET` | Yes | Secret used to sign generated download links. Use a long random value. |
| `DOWNLOAD_LINK_TTL_SECONDS` | Yes | Link expiration time (in seconds) for generated download links. |

Generate a strong value for `DOWNLOAD_LINK_SECRET` (example):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Services in `docker-compose.yml`

- `bot`: Telegram bot application.
- `qbittorrent`: torrent engine + Web UI.
- `file-server`: serves completed downloads over HTTP.
- `nginxproxymanager`: reverse proxy manager that can be used for HTTPS/SSL and routing.

### Why `nginxproxymanager` is included

`nginxproxymanager` is included for **potential SSL enforcement** and URL routing, including:
- redirecting custom domain URLs to qBittorrent Web UI,
- redirecting custom domain URLs to the HFS/file-server endpoint,
- optionally enforcing HTTP → HTTPS.

Default Nginx Proxy Manager admin UI: `http://localhost:81`.

## qBittorrent first-run notes

- The LinuxServer qBittorrent container emits a temporary admin password on first startup.
- You must use that password once to log in and set your final credentials.
- After setting final credentials, restart the full compose stack so the bot consistently authenticates with the updated values.

## Available bot commands

### General
- `/start` — entry command.
- `/authenticate <token>` — authenticate and join whitelist.
- `/cancel` — cancel the currently pending multi-step command input.

### Whitelisted users
- `/queuedownload` — queue a torrent file or magnet link.
- `/status` — view current torrent progress.
- `/canceldownload` — cancel and remove an active download.
- `/getdownloadlink` — get a link for a finished download.
- `/deletefiles` — delete finished downloads.
- `/myfolder` — get your personal folder link.

### Admin only (owner)
- `/generateaccesstoken` — generate one-time authentication token.
- `/removeuser <user_id>` — remove a user from whitelist.
- `/whitelist` — list whitelisted users.
- `/availablespace` — show available disk space.

## Common operations

Start/restart:

```bash
docker compose up -d --build
```

Stop:

```bash
docker compose down
```

View logs:

```bash
docker compose logs -f bot
docker compose logs -f qbittorrent
```

## Notes

- Keep your `.env` out of version control.
- Use strong secrets/passwords in production.
- If you put qBittorrent and file server behind a public domain, configure TLS via `nginxproxymanager`.
