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
     volumes/qbittorrent_config
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

   - Open the qBittorrent Web UI and sign in with the temporary password. The Web UI is
     bound to `127.0.0.1:8080`, so reach it from the server itself (`http://localhost:8080`),
     over an SSH tunnel, or via your qBittorrent subdomain through the reverse proxy.
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
| `TELEGRAM_BOT_TOKEN` | Yes | Telegram Bot token from BotFather. |
| `TELEGRAM_API_ID` | Yes | Telegram API id from [my.telegram.org](https://my.telegram.org). Required because the bot speaks MTProto (Telethon), not the HTTP Bot API. |
| `TELEGRAM_API_HASH` | Yes | Telegram API hash from [my.telegram.org](https://my.telegram.org). |
| `BOT_OWNER_USER_ID` | Yes | Telegram `user_id` of the bot owner/admin (allowed to run admin-only commands). |
| `TELEGRAM_MTPROXY` | No | Initial MTProto proxy for reaching Telegram when it is blocked. Seeds the proxy store on first boot only (thereafter the store is the source of truth). See [Reaching Telegram through a proxy](#reaching-telegram-through-a-proxy). |
| `TELEGRAM_SESSION_PATH` | No | Where Telethon persists its session (default `/auth/bot.session`). Persisting it avoids re-doing the auth handshake on every restart. |
| `ADMIN_WEB_USERNAME` | No | Username for the proxy admin page. Leave blank (with the password) to disable the page. |
| `ADMIN_WEB_PASSWORD` | No | Password for the proxy admin page. Must be at least 16 characters — the page is exposed to the public internet. |
| `ADMIN_WEB_PORT` | No | Port the admin page listens on (default `8082`). Published on `127.0.0.1` only, so it is reachable through your host's reverse proxy (which terminates HTTPS) but not exposed as plaintext on the public IP. |
| `QBITTORRENT_URL` | Yes | qBittorrent Web UI/API URL used by the bot (for Docker Compose default: `http://qbittorrent:8080`). |
| `QBITTORRENT_USERNAME` | Yes | qBittorrent Web UI username used by the bot API client. |
| `QBITTORRENT_PASSWORD` | Yes | qBittorrent Web UI password used by the bot API client. |
| `TORRENT_INPUT_TMP_DIR` | Yes | Temp folder inside the bot container for uploaded `.torrent` files before queueing. |
| `AUTH_DB_PATH` | Yes | SQLite file path for whitelist/auth data (default compose path: `/auth/auth.db`). |
| `ACTIVE_DOWNLOADS_ROOT` | Yes | Path where in-progress torrent data is stored. |
| `FINISHED_DOWNLOADS_ROOT` | Yes | Path where completed downloads are stored (served by file server). |
| `DOWNLOADS_ROOT` | No | Broader root qBittorrent saves into (default `/downloads`). Torrents queued directly via the qBittorrent Web UI are swept up from here and moved under `FINISHED_DOWNLOADS_ROOT/<BOT_OWNER_USER_ID>/`. See [Queueing without Telegram](#queueing-without-telegram-fallback). |
| `DOWNLOAD_RECORDS_DB_PATH` | Yes | SQLite path used to track download records/metadata. |
| `FINISHED_DOWNLOAD_RETENTION_DAYS` | Yes | Retention period for completed downloads/records. |
| `HFS_BASE_URL` | Yes | **Base URL for the file server** used when generating user download links. |
| `DOWNLOAD_LINK_SECRET` | Yes | Secret used to sign generated download links. Use a long random value. |
| `DOWNLOAD_LINK_TTL_HOURS` | No | Link expiration time in hours for generated download links (default `24`). |

Generate a strong value for `DOWNLOAD_LINK_SECRET` (example):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Services in `docker-compose.yml`

- `bot`: Telegram bot application (Telethon/MTProto). Also hosts the optional proxy
  admin page on `ADMIN_WEB_PORT` (published on `127.0.0.1` only). See
  [Reaching Telegram through a proxy](#reaching-telegram-through-a-proxy).
- `qbittorrent`: torrent engine + Web UI (Web UI published on `127.0.0.1:8080`; the
  BitTorrent peer port `6881` stays public so peers can connect).
- `file-server`: serves completed downloads over HTTP (published on `127.0.0.1:8081`).

The three HTTP surfaces (qBittorrent Web UI, file server, proxy admin page) are published
on `127.0.0.1` only, so they are never exposed as plaintext on the public IP. Reach them
through a reverse proxy on the host (nginx + Let's Encrypt, Caddy, etc.) that terminates
HTTPS and maps your subdomains to `127.0.0.1:8080` / `:8081` / `:8082`. This repo no
longer ships its own reverse-proxy container.

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

## Reaching Telegram through a proxy

Where Telegram is blocked or throttled, the bot can reach it through an **MTProto
proxy**. Because the bot uses Telethon (MTProto) rather than the HTTP Bot API, it can
use MTProto proxies of any secret format, including FakeTLS (`ee`) proxies produced by
`mtg`. SOCKS5 proxies (`socks5://host:port`) also work.

**Failover.** The active proxy lives in a small store on the `/auth` volume
(`/auth/proxies.json`), seeded from `TELEGRAM_MTPROXY` on first boot. You can list
several proxies; the bot tries the active one and automatically rotates to the next when
a connection fails, retrying every 30 seconds. The download workers keep running while it
retries, because they only talk to qBittorrent.

**Proxy string forms** (any of these, one per line in the store):

- `tg://proxy?server=HOST&port=PORT&secret=SECRET`
- `https://t.me/proxy?server=HOST&port=PORT&secret=SECRET`
- `HOST:PORT:SECRET`
- `socks5://HOST:PORT` (or `socks5://user:pass@HOST:PORT`)
- `direct` — connect straight to Telegram with no proxy

**Test a proxy from the server** without restarting the stack:

```bash
docker compose exec bot python -m app.tools.check_telegram
# or check a specific proxy string:
docker compose exec bot python -m app.tools.check_telegram "tg://proxy?server=..&port=..&secret=.."
```

It prints the detected secret type, the connection class, and the bot's own username on
success; it exits non-zero on failure.

### Changing proxies from a browser (admin page)

Set `ADMIN_WEB_USERNAME` and `ADMIN_WEB_PASSWORD` (password ≥ 16 chars) to enable a
minimal web page for editing the proxy list without SSH. It runs inside the bot process
(so it stays reachable exactly when Telegram is down) and is published on `127.0.0.1`
only. Expose it the same way your other subdomains are served — through the reverse
proxy already running on the host, which terminates HTTPS:

1. Point a subdomain (e.g. `proxy.<your-domain>`) at the server, like `files.<your-domain>`.
2. In that reverse proxy, add a virtual host for it forwarding to `127.0.0.1:8082`
   (`ADMIN_WEB_PORT`) with the existing Let's Encrypt setup.

Because TLS is terminated at the reverse proxy and the port is bound to localhost, the
basic-auth password is never sent in cleartext over the network. Saving the form
validates every entry, writes the store, and forces an immediate reconnect through the
new active proxy.

## Queueing without Telegram (fallback)

Even with a proxy configured, Telegram may still be unreachable (every proxy blocked, or
the proxy itself down). In that case the bot cannot receive commands or deliver links —
but the background worker that moves and exposes finished downloads keeps running, because
it only talks to qBittorrent locally. You can still queue and retrieve downloads:

1. **Queue the torrent in the qBittorrent Web UI** (`http://localhost:8080`). Either:
   - set **Save files to location** to `${ACTIVE_DOWNLOADS_ROOT}/<your_telegram_user_id>` to attribute it to a specific user, or
   - just queue it with the default save location — anything under `DOWNLOADS_ROOT` is automatically attributed to `BOT_OWNER_USER_ID`.

2. **Wait for completion.** The worker moves the payload into
   `FINISHED_DOWNLOADS_ROOT/<user_id>/` and exposes it through the file server, exactly
   as it does for bot-queued torrents.

3. **Generate a download link from the command line** (since the bot can't send it):

   ```bash
   # Link to the owner's folder (uses BOT_OWNER_USER_ID):
   docker compose exec bot python -m app.tools.make_link

   # Or link to a specific user's folder:
   docker compose exec bot python -m app.tools.make_link <user_id>
   ```

   This prints an expiring signed link to that user's folder. The file server has
   directory listing enabled and sets an auth cookie, so a single folder link lets you
   browse and download everything under it until the link expires.

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
- If you put qBittorrent, the file server, or the proxy admin page behind a public
  domain, terminate TLS at a reverse proxy on the host (nginx + Let's Encrypt, Caddy, etc.).
