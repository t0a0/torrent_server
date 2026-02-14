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
   ```

6. Start the bot:
   ```bash
   python3 -m app.bot.main
   ```

## Phase 1 command flow

- `/generateaccesstoken` (admin only): creates a secure, single-use token valid for 30 minutes.
- `/authenticate <token>`: redeems token, whitelists caller by Telegram `user_id`, and stores username at authentication time.
- `/whitelist` (admin only): lists whitelisted users.
- `/removeuser <user_id>` (admin only): removes a user from whitelist.
- `/start`: available to everyone, but non-whitelisted users are prompted to authenticate first.
- `/add`: available only for whitelisted users.

## Telegram command menu

The bot now configures Telegram command menus programmatically at startup:

- Non-whitelisted users see: `/start`, `/authenticate`.
- Whitelisted users see: `/start`, `/add` (without `/authenticate`).
- Owner chat (using `BOT_OWNER_USER_ID`) gets whitelisted commands plus admin commands via `BotCommandScopeChat`: `/generateaccesstoken`, `/removeuser`, `/whitelist`.
- Menus are updated dynamically when a user authenticates or is removed from whitelist.

This is applied automatically in `run_bot()` before polling starts.



## Phase 2 torrent service primitives

A qBittorrent-backed service now lives in `app/torrent/service.py` with two methods:

- `start_download_from_file_bytes(user_id, torrent_file_bytes)`
- `start_download_from_magnet_url(user_id, magnet_url)`

Both methods store download payloads under `downloads/<user_id>/...` (or `DOWNLOADS_ROOT/<user_id>/...` if configured).
