# AGENTS.md

This file defines how coding agents should work in this repository.
Scope: entire repository.

## Project goal
Build a **private torrent queue + delivery server** controlled through a Telegram bot.

- Users submit magnet links/torrent files via Telegram bot.
- Server queues and downloads via qBittorrent.
- Bot reports status/progress.
- Completed files are delivered via **expiring HTTPS download links** (not Telegram upload).

## Guiding principles
1. **Simplicity first**: prefer straightforward, maintainable solutions.
2. **Reasonable security by default**: never ship obviously unsafe defaults.
3. **Operational clarity**: include practical run/debug steps in docs.
4. **Small iterations**: implement in increments that can be tested.

## Approved stack (v1)
- **OS/host**: Ubuntu VPS
- **Container runtime**: Docker + Docker Compose
- **Torrent engine**: qBittorrent-nox (Web API)
- **Bot/API service**: Python 3.12
- **Telegram library**: aiogram
- **Storage**: SQLite (initially)
- **Reverse proxy/TLS (when public links are enabled)**: Caddy or Nginx

Do not introduce extra infrastructure (Kubernetes, message brokers, Redis, Postgres) unless requested.

## Security baseline (must follow)
- Do **not** expose qBittorrent Web UI/port to public internet.
- Keep secrets in `.env` files; never hardcode tokens/passwords.
- Restrict bot commands to an allowlist of Telegram user IDs.
- Download links must be tokenized and expiring.
- Prefer least-privilege container/user permissions where practical.
- Document any security tradeoff in PR notes.

## Functional priorities
1. Queue torrents from Telegram commands.
2. Track and report status/progress/errors.
3. Generate expiring download links for completed files.
4. Basic cleanup/retention controls to avoid disk exhaustion.

## Non-goals for now
- Multi-tenant public service.
- Horizontal scaling / high availability.
- Complex admin UI.

## Coding conventions
- Keep modules small and focused.
- Add type hints to public Python functions.
- Prefer explicit names over clever abstractions.
- Add or update tests for queue/state/link-token logic.
- Avoid dead code and commented-out blocks.

## Documentation requirements
When adding features, update docs with:
- How to configure environment variables.
- How to run locally and in Docker Compose.
- How to verify feature behavior.
- Any security/ops considerations (disk usage, cleanup, access controls).

## Validation checklist before finishing work
Run relevant commands based on repo contents. Typical examples:
- `docker compose config`
- `pytest -q`
- `ruff check .`

If a command cannot run due to environment limits, report that clearly.

## Interaction mode defaults
- Default to **Q&A mode** (chat-only response, no file edits) unless the user explicitly asks to implement, patch, or commit code.
- Enter **Implementation mode** only when the user explicitly requests code/config/file changes.
- If intent is ambiguous, prefer a brief clarifying chat response over making repository changes.

## Change discipline
- Keep diffs minimal and task-focused.
- Do not perform unrelated refactors.
- If unsure between options, choose the simpler one and note alternatives briefly.
