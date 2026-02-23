# AGENTS.md

## Project overview
This repository is for a **torrent server controlled by a Telegram bot**.

Primary stack and constraints:
- Python (latest stable version)
- Telegram bot API via `aiogram`
- Torrent control via `python-qbittorrent`
- Docker for build and deployment
- SQLite for auth/whitelist persistence

## Working mode defaults
- Unless explicitly asked to implement/code, operate in **Q/A mode** (no file modifications).
- No tests are required by default unless explicitly requested.
- Avoid module-level cached variables for simple configuration getter calls; prefer calling small config functions at usage sites unless caching is required for correctness/performance.
- For user-facing torrent name display, always use the final display name truncated to the first 64 characters.

- For Docker bind mounts, use paths under `./volumes/...` and ensure committed placeholder files (`.gitkeep`) exist for mounted directories.

## Product roadmap context

### Phase 1 (Bot and access control)
Implement bot command handling and user authorization:
- `/start`
- `/queuedownload`
- `/removeuser <user_id>`
- `/generateaccesstoken`
- `/authenticate <token>`
- `/whitelist`

Authorization rules:
- Only authenticated/whitelisted users (stored by Telegram `user_id`) can use `/start` and `/queuedownload`.
- `/generateaccesstoken`, `/removeuser`, and `/whitelist` are **admin-only**.
- Admin-only means only the owner account (project maintainer) can run those commands.
- Any user can call `/authenticate <token>`; valid non-expired tokens whitelist that caller `user_id`.

### Phase 2 (Torrent engine and download delivery)
Integrate qBittorrent operations:
- Add torrent by file and by magnet link.
- Download torrent payload to local server storage.
- First iteration: generate the **simplest working download URL** for completed files (static URL is acceptable).
- Later iteration (optional hardening): switch to **short-lived tokenized URLs**.
- Delete torrent from queue.
- Auto-delete torrent from queue after download completion.

### Phase 3 (Bot + torrent integration)
Connect phase 1 and phase 2 behavior:
- `/queuedownload` should queue a torrent/magnet for download.
- When download completes, notify the initiating Telegram user with the generated download link.

## Implementation expectations for future tasks
When implementing features in this repository, prefer:
- Clear separation of concerns (Telegram handlers, auth/whitelist service, torrent service, download-link service).
- Configuration through environment variables (bot token, owner user_id, storage paths, qBittorrent connection, token TTL, etc.).
- Docker-first setup for local and server execution.
- Async-friendly design to align with `aiogram` and background task/event handling.

## Security and access notes
- Treat whitelist and owner checks as mandatory guardrails.
- Validate usernames and command inputs.
- For first iteration, static URLs are acceptable for speed of delivery.
- If/when tokenized URLs are introduced, they must be expiring and unguessable.
- Restrict file serving to expected download directories.
- For HTTPS deployments using cookie-assisted auth, remember to set auth cookies with the `Secure` attribute and enforce HTTP->HTTPS redirect (or block plain HTTP) at the edge.

## Suggested command behavior reference
- `/start`: available to everyone; if caller is not whitelisted, respond with authentication guidance.
- `/queuedownload`: accept magnet link or torrent file and queue download (whitelisted users only).
- `/generateaccesstoken`: owner-only; create a single-use access token (30-minute TTL).
- `/authenticate <token>`: redeem a valid token and whitelist caller by `user_id`; hide this command from menu once user is whitelisted.
- `/removeuser <user_id>`: owner-only; remove user from whitelist by `user_id`; show `/authenticate` in removed user menu again.
- `/whitelist`: owner-only; list whitelisted users (`user_id`, username at authentication).
- Command menu expectations: non-whitelisted users see `/start` + `/authenticate`; whitelisted users see `/start` + `/queuedownload`; owner sees whitelisted + admin commands.

## Out-of-scope unless requested
- UI/front-end work.
- Automated test suite creation.
- Additional bot commands beyond listed roadmap.
