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
   ```

6. Start the bot:
   ```bash
   python3 -m app.bot.main
   ```


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
DOWNLOADS_ROOT=downloads
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

### Start the full stack

1. Start qBittorrent Web UI/API (local app or VPS container).
2. Start the bot:

```bash
python3 -m app.bot.main
```

> Note: at the moment `/add` is still a placeholder handler and does not yet call `TorrentService`. Phase 3 will wire bot messages/files into qBittorrent.



For Docker Compose deployments, set:

```env
DOWNLOADS_ROOT=/downloads
HFS_BASE_URL=http://localhost:8081
DOWNLOAD_LINK_SECRET=replace_with_long_random_secret
DOWNLOAD_LINK_TTL_SECONDS=1800
```

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

All torrent payloads are stored in a shared Docker volume (`downloads`) mounted into both `qbittorrent` and `file-server`.

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
- Changes under `./app` are synced with `sync+restart` behavior.
- Changes to `Dockerfile` trigger a rebuild for `bot`.

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
docker compose exec qbittorrent sh -lc 'mkdir -p /downloads/<telegram_user_id> && echo hello > /downloads/<telegram_user_id>/test.txt'
```

5. Open the `/myfolder` URL in a browser and confirm `test.txt` appears.

Notes:
- `/srv/downloads` is inside the `file-server` container and mounted read-only there.
- Use `/downloads` in `qbittorrent` for manual test writes because both containers share the same Docker volume.


## Phase 1 command flow

- `/generateaccesstoken` (admin only): creates a secure, single-use token valid for 30 minutes.
- `/authenticate <token>`: redeems token, whitelists caller by Telegram `user_id`, and stores username at authentication time.
- `/whitelist` (admin only): lists whitelisted users.
- `/removeuser <user_id>` (admin only): removes a user from whitelist.
- `/start`: available to everyone, but non-whitelisted users are prompted to authenticate first.
- `/add`: available only for whitelisted users.
- `/myfolder`: available only for whitelisted users; returns an expiring signed HTTPS link to `downloads/<user_id>/`.

## Telegram command menu

The bot now configures Telegram command menus programmatically at startup:

- Non-whitelisted users see: `/start`, `/authenticate`.
- Whitelisted users see: `/start`, `/add`, `/myfolder` (without `/authenticate`).
- Owner chat (using `BOT_OWNER_USER_ID`) gets whitelisted commands plus admin commands via `BotCommandScopeChat`: `/generateaccesstoken`, `/removeuser`, `/whitelist`.
- Menus are updated dynamically when a user authenticates or is removed from whitelist.

This is applied automatically in `run_bot()` before polling starts.




## HFS per-user folder links

`/myfolder` generates an expiring signed URL for the caller only. The URL path is always `<HFS_BASE_URL>/<telegram_user_id>/` and includes `expires`, `nonce`, and `sig` query params.

Security behavior:
- The bot only serves `/myfolder` to whitelisted users.
- The link signature is NGINX `secure_link` compatible (`MD5` + base64url) over `expires + uri + nonce + " " + DOWNLOAD_LINK_SECRET`.
- Links expire after `DOWNLOAD_LINK_TTL_SECONDS` (default 1800 seconds).
- The folder mapping is fixed to `downloads/<user_id>/`, so user `123` only gets links to `downloads/123/`.

> Deploy HFS behind HTTPS as planned. The generated links are intended for HTTPS public exposure.

NGINX now enforces both signature and expiry checks at request time, returning `403` for invalid signatures and `410` for expired links.

## Phase 2 torrent service primitives

A qBittorrent-backed service now lives in `app/torrent/service.py` with two methods:

- `start_download_from_file_bytes(user_id, torrent_file_bytes)`
- `start_download_from_magnet_url(user_id, magnet_url)`

Both methods store download payloads under `downloads/<user_id>/...` (or `DOWNLOADS_ROOT/<user_id>/...` if configured).

The service also runs a background cleanup loop that automatically removes completed torrents from the qBittorrent queue (for all users) to stop seeding. Downloaded files are kept on disk (`delete_files=False`). The cleanup interval defaults to 30 seconds.
