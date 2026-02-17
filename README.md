# Torrent Server Bot

## Running the bot

1. Create a Python virtual environment:
   ```bash
   python3 -m venv .venv
   ```

2. Activate the virtual environment:
   ```bash
   source .venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install --upgrade pip
   pip install aiogram python-qbittorrent
   ```

4. Create your local environment file:
   ```bash
   cp .env.example .env
   ```

5. Edit `.env` and set your Telegram bot settings:
   ```env
   TELEGRAM_BOT_TOKEN=your_real_bot_token
   BOT_OWNER_USER_ID=123456789
   HFS_BASE_URL=https://files.example.com
   DOWNLOAD_LINK_SECRET=replace_with_long_random_secret
   DOWNLOAD_LINK_TTL_SECONDS=1800
   AUTH_DB_PATH=auth.db
   ```

6. Start the bot:
   ```bash
   python3 -m app.bot.main
   ```



## Auth persistence (SQLite)

Whitelist/auth data is persisted in an SQLite database instead of in-memory state.

- The bot reads the database location from `AUTH_DB_PATH` (default: `auth.db`).
- In Docker Compose, the bot stores this file at `/auth/auth.db` on a dedicated `auth_data` volume.
- Recreating/updating the bot container keeps whitelist data as long as the `auth_data` volume is preserved.

## Running qBittorrent (required for Phase 2)

The Telegram bot and qBittorrent run as separate processes. Start qBittorrent first, then start the bot.

### Local macOS

1. Install and open qBittorrent (GUI app).
2. In qBittorrent settings, enable Web UI (HTTP API).
3. Configure host/port/credentials (example: `127.0.0.1:8080`).
4. Set matching values in `.env`:

```env
QBITTORRENT_URL=http://127.0.0.1:8080
QBITTORRENT_USERNAME=<your_webui_username>
QBITTORRENT_PASSWORD=<your_webui_password>
DOWNLOADS_ROOT=finished_downloads
ACTIVE_DOWNLOADS_ROOT=active_downloads
QBIT_GLOBAL_UPLOAD_LIMIT_BYTES_PER_SEC=1048576
```

### VPS (Docker example)

```bash
docker run -d \
  --name qbittorrent \
  -e PUID=1000 \
  -e PGID=1000 \
  -e TZ=UTC \
  -e WEBUI_PORT=8080 \
  -p 8080:8080 \
  -p 6881:6881 \
  -p 6881:6881/udp \
  -v /opt/qbit/config:/config \
  -v /opt/qbit/downloads:/downloads \
  --restart unless-stopped \
  lscr.io/linuxserver/qbittorrent:latest
```

After container startup, open `http://<vps_ip>:8080`, configure credentials, and copy the same values into `.env`.

### qBittorrent first-start credentials and bot login behavior

If you use `lscr.io/linuxserver/qbittorrent`, first container boot prints a **temporary WebUI password** in logs.
That temporary password is only for initial setup. After you sign in and set your own password in qBittorrent WebUI,
store that final username/password in `.env` as:

```env
QBITTORRENT_USERNAME=admin
QBITTORRENT_PASSWORD=<your_final_password>
```

Important notes:
- The image does not provide a stable "set WebUI username/password via env" mechanism for this project.
- The password you set in WebUI is persisted under the mounted `/config` volume, so you only do this once per config volume.
- The bot authenticates lazily: it checks/login when a torrent API call is made. This avoids startup coupling to qBittorrent readiness.
- Yes, qBittorrent API sessions can expire (cookie/session timeout or container restart). The bot handles this by re-authenticating when `LoginRequired` is raised.

### Start the full stack

1. Start qBittorrent Web UI/API (local app or VPS container).
2. Start the bot:

```bash
python3 -m app.bot.main
```


For Docker Compose deployments, set:

```env
DOWNLOADS_ROOT=/downloads/finished_downloads
ACTIVE_DOWNLOADS_ROOT=/downloads/active_downloads
HFS_BASE_URL=http://localhost:8081
DOWNLOAD_LINK_SECRET=replace_with_long_random_secret
DOWNLOAD_LINK_TTL_SECONDS=1800
```

`docker-compose.yml` intentionally reads these from `.env` (via `env_file`) so the path values are defined in one place.

Generate a strong random secret for `DOWNLOAD_LINK_SECRET` (example):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```


## Docker Compose stack (bot + qBittorrent + HFS file-server)

A ready-to-run `docker-compose.yml` is included for running the full stack with a dedicated **file-server container** that exposes downloaded files over HTTP.

### Services

- `bot`: Telegram bot process (`python -m app.bot.main`).
- `qbittorrent`: torrent engine and Web UI (`http://localhost:8080`).
- `file-server`: NGINX-based HFS (HTTP file server) exposing the shared downloads volume (`http://localhost:8081`).

Active torrent payloads are stored under `downloads/active_downloads` on the shared `downloads` Docker volume mounted into both `bot` and `qbittorrent`.

When a torrent completes, it is removed from qBittorrent and then moved into the shared `downloads` volume served by `file-server`.

Auth/whitelist records are stored in a separate SQLite file on a dedicated Docker volume (`auth_data`) mounted into the `bot` service at `/auth/auth.db`.

### Start

```bash
cp .env.example .env
# Edit .env and set all the variables
docker compose up -d --build
```

### Faster local iteration (no rebuild on every code change)

For day-to-day bot development, use Docker Compose Watch to sync `./app` changes into the running `bot` container and restart only that service process:

```bash
docker compose watch bot
```

Notes:
- Keep `docker compose up -d` running in another terminal.
- `docker compose up` **alone** does not enable live syncing/restart behavior.
- You generally do **not** need to toggle anything in Docker Desktop settings for this project-specific workflow.
- Changes under `./app` are synced with `sync+restart` behavior.
- Changes to `Dockerfile` trigger a rebuild for `bot`.

If hot reload seems broken, first confirm the watch process is actually running:

```bash
docker compose watch bot
docker compose logs -f bot
```

Then edit a file under `./app` and verify the bot service restarts.

Once torrents are downloaded, files become browseable via the file server at:

```text
http://localhost:8081/<telegram_user_id>/
```

### Local end-to-end smoke test for `/myfolder`

1. Bring up the stack (`docker compose up -d --build`).
2. In Telegram, authenticate a user (`/generateaccesstoken` then `/authenticate <token>`).
3. Run `/myfolder` and copy the returned signed URL.
4. Create a test file in that user's folder via the **write-capable** qBittorrent container:

```bash
docker compose exec qbittorrent sh -lc 'mkdir -p /downloads/finished_downloads/<telegram_user_id> && echo hello > /downloads/finished_downloads/<telegram_user_id>/test.txt'
```

5. Open the `/myfolder` URL in a browser and confirm `test.txt` appears.

Notes:
- `/srv/downloads` is inside the `file-server` container and mounted read-only there.
- Use `/downloads/finished_downloads` in `qbittorrent` for manual test writes because both containers share the same Docker volume.


## Phase 1 command flow

- `/generateaccesstoken` (admin only): creates a secure, single-use token valid for 30 minutes.
- `/authenticate <token>`: redeems token, whitelists caller by Telegram `user_id`, and stores username at authentication time.
- `/whitelist` (admin only): lists whitelisted users.
- `/removeuser <user_id>` (admin only): removes a user from whitelist.
- `/start`: available to everyone, but non-whitelisted users are prompted to authenticate first.
- `/queuedownload`: available only for whitelisted users.
- `/canceldownload`: available only for whitelisted users; lets the user pick an active torrent and cancel/delete it (including downloaded files).
- `/myfolder`: available only for whitelisted users; returns an expiring signed HTTPS link to `finished_downloads/<user_id>/`.

## Telegram command menu

The bot now configures Telegram command menus programmatically at startup:

- Non-whitelisted users see: `/start`, `/authenticate`.
- Whitelisted users see: `/start`, `/queuedownload`, `/canceldownload`, `/myfolder` (without `/authenticate`).
- Owner chat (using `BOT_OWNER_USER_ID`) gets whitelisted commands plus admin commands via `BotCommandScopeChat`: `/generateaccesstoken`, `/removeuser`, `/whitelist`.
- Menus are updated dynamically when a user authenticates or is removed from whitelist.

This is applied automatically in `run_bot()` before polling starts.




## HFS per-user folder links

`/myfolder` generates an expiring signed URL for the caller only. The URL path is always `<HFS_BASE_URL>/<telegram_user_id>/` and includes `expires`, `nonce`, and `sig` query params.

Security behavior:
- The bot only serves `/myfolder` to whitelisted users.
- The link signature is NGINX `secure_link` compatible (`MD5` + base64url) over `expires + uri + nonce + " " + DOWNLOAD_LINK_SECRET`.
- Links expire after `DOWNLOAD_LINK_TTL_SECONDS` (default 1800 seconds).
- The folder mapping is fixed to `finished_downloads/<user_id>/`, so user `123` only gets links to `finished_downloads/123/`.

> Deploy HFS behind HTTPS as planned. The generated links are intended for HTTPS public exposure.

NGINX now enforces both signature and expiry checks at request time, returning `403` for invalid signatures and `410` for expired links.

## Phase 2 torrent service primitives

A qBittorrent-backed service now lives in `app/torrent/service.py` with two methods:

- `start_download_from_file_bytes(user_id, torrent_file_bytes)`
- `start_download_from_magnet_url(user_id, magnet_url)`

Both methods store active payloads under `active_downloads/<user_id>/...` (or `ACTIVE_DOWNLOADS_ROOT/<user_id>/...` if configured).

The service also runs a background cleanup loop that automatically removes completed torrents from the qBittorrent queue (for all users) to stop seeding. After removal, payload files are moved into `finished_downloads/<user_id>/...` (`DOWNLOADS_ROOT`) for `/myfolder` delivery. The cleanup interval defaults to 30 seconds.


## Phase 3 `/queuedownload` validation and queue flow

- `/queuedownload` now starts an input session and prompts user to paste a magnet URL or upload a `.torrent` file.
- Both input types go through validation gates (size, structure, btih parsing/normalization, and dedupe checks).
- Valid payloads are queued via qBittorrent into `ACTIVE_DOWNLOADS_ROOT/<telegram_user_id>/`.
- Duplicate/invalid/backend errors are mapped to stable user-safe bot messages.

## `/status` live progress behavior

- `/status` is available to whitelisted users and reports active queued/downloading torrents scoped to the caller `user_id`.
- Progress percentages are read live from qBittorrent torrent state (`progress` 0..1 => 0..100%).
- No in-memory dictionary is required for status tracking.
- No SQLite status table is required for live status tracking.
- If product requirements later need history/audit (for example, recent completed torrents), that can be persisted separately while keeping live progress sourced from qBittorrent.
- Uploaded `.torrent` files are stored in a temporary path (`TORRENT_INPUT_TMP_DIR`) and always removed after processing.

### Troubleshooting: `file_open ... Permission denied` in qBittorrent

If qBittorrent reports a permission error under `/downloads/active_downloads/<telegram_user_id>/...`, ensure `ACTIVE_DOWNLOADS_ROOT` points inside the shared `/downloads` mount for both bot and qBittorrent (the default Compose setup uses `/downloads/active_downloads`).

Current behavior avoids pre-creating user subfolders from the bot side; qBittorrent creates/uses the active save path itself. For already-created folders, fix ownership/permissions on the shared downloads volume so qBittorrent can write there.

Global upload limit is configured via `QBIT_GLOBAL_UPLOAD_LIMIT_BYTES_PER_SEC` (default `1048576`, i.e. 1 MiB/s). On service startup, the bot applies this value to qBittorrent via the Web API preferences (`up_limit`).

