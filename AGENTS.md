# AGENTS.md

## Project overview
This repository is for a **torrent server controlled by a Telegram bot**.

Primary stack and constraints:
- Python (latest stable version)
- Telegram bot API via `aiogram`
- Torrent control via a qBittorrent Python library
- Docker for build and deployment

## Working mode defaults
- Unless explicitly asked to implement/code, operate in **Q/A mode** (no file modifications).
- No tests are required by default unless explicitly requested.

## Product roadmap context

### Phase 1 (Bot and access control)
Implement bot command handling and user authorization:
- `/start`
- `/add`
- `/adduser <username>`
- `/removeuser <username>`
- `/whitelist`

Authorization rules:
- Only **whitelisted usernames** can interact with the bot.
- `/adduser`, `/removeuser`, and `/whitelist` are **admin-only**.
- Admin-only means only the owner username (project maintainer) can run those commands.
- Other whitelisted users can use non-admin commands like `/start` and `/add`, but not admin commands.

### Phase 2 (Torrent engine and download delivery)
Integrate qBittorrent operations:
- Add torrent by file and by magnet link.
- Download torrent payload to local server storage.
- Generate a **short-lived tokenized URL** for downloading completed files.
- Delete torrent from queue.
- Auto-delete torrent from queue after download completion.

### Phase 3 (Bot + torrent integration)
Connect phase 1 and phase 2 behavior:
- `/add` should queue a torrent/magnet for download.
- When download completes, notify the initiating Telegram user with the generated download link.

## Implementation expectations for future tasks
When implementing features in this repository, prefer:
- Clear separation of concerns (Telegram handlers, auth/whitelist service, torrent service, download-link service).
- Configuration through environment variables (bot token, owner username, storage paths, qBittorrent connection, token TTL, etc.).
- Docker-first setup for local and server execution.
- Async-friendly design to align with `aiogram` and background task/event handling.

## Security and access notes
- Treat whitelist and owner checks as mandatory guardrails.
- Validate usernames and command inputs.
- Tokenized download URLs must be expiring and unguessable.
- Restrict file serving to expected download directories.

## Suggested command behavior reference
- `/start`: greet user and explain available commands based on role.
- `/add`: accept magnet link or torrent file and queue download.
- `/adduser <username>`: owner-only; add username to whitelist.
- `/removeuser <username>`: owner-only; remove username from whitelist.
- `/whitelist`: owner-only; list whitelisted usernames.

## Out-of-scope unless requested
- UI/front-end work.
- Automated test suite creation.
- Additional bot commands beyond listed roadmap.
