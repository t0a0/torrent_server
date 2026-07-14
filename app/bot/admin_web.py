"""Minimal proxy-admin web page, served from a daemon thread in the bot process.

One HTML form to view and edit the proxy list without SSHing into the server. It lives
inside the bot process on purpose: the retry loop keeps the process alive precisely
when Telegram is unreachable, which is exactly when this page is needed. It uses only
the standard library (no new dependencies).

Security posture (the page sits behind nginx-proxy-manager on the public internet, so
credentials must travel over HTTPS — enforce "Force SSL" on the NPM proxy host):
- HTTP basic auth, credentials from .env, compared with ``secrets.compare_digest``.
- The caller (main) only starts this when both credentials are set, and refuses a
  password shorter than 16 chars.
- Per-IP failed-attempt backoff to blunt brute forcing.
- ``Cache-Control: no-store``; proxy secrets are never written to the logs.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from base64 import b64decode
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from .mtproxy import ProxyError
from .proxy_store import ProxyStore
from .runtime import runtime

logger = logging.getLogger(__name__)

_MAX_FAILURES = 5
_LOCKOUT_WINDOW_SECONDS = 300


class _FailureTracker:
    """Per-IP failed-auth counter with a sliding lockout window."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._failures: dict[str, list[float]] = {}

    def is_locked(self, ip: str) -> bool:
        now = time.time()
        with self._lock:
            recent = [t for t in self._failures.get(ip, []) if now - t < _LOCKOUT_WINDOW_SECONDS]
            self._failures[ip] = recent
            return len(recent) >= _MAX_FAILURES

    def record_failure(self, ip: str) -> None:
        with self._lock:
            self._failures.setdefault(ip, []).append(time.time())

    def clear(self, ip: str) -> None:
        with self._lock:
            self._failures.pop(ip, None)


def _render_page(proxy_store: ProxyStore, message: str | None = None) -> str:
    snapshot = proxy_store.snapshot()
    status = runtime.get_status()
    entries_text = escape("\n".join(snapshot.entries))
    updated = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(status.updated_at))
    status_color = {"connected": "#128a12", "failed": "#b00020"}.get(status.state, "#666")
    error_html = (
        f'<p><b>Last error:</b> <code>{escape(status.last_error)}</code></p>'
        if status.last_error
        else ""
    )
    flash_html = f'<p style="color:#128a12"><b>{escape(message)}</b></p>' if message else ""

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Proxy admin</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; }}
  textarea {{ width: 100%; font-family: monospace; }}
  .status {{ padding: .5rem .75rem; border-left: 4px solid {status_color}; background:#f6f6f6; }}
  input[type=number] {{ width: 5rem; }}
  button {{ padding: .5rem 1rem; font-size: 1rem; }}
  code {{ word-break: break-all; }}
</style></head><body>
<h1>Telegram proxy</h1>
{flash_html}
<div class="status">
  <p><b>Connection:</b> <span style="color:{status_color}">{escape(status.state)}</span>
     via {escape(status.proxy_description)}</p>
  {error_html}
  <p style="color:#888;font-size:.85em">Updated {updated}</p>
</div>
<form method="post" action="/">
  <p>One proxy per line. Accepted forms: <code>tg://proxy?...</code>,
     <code>https://t.me/proxy?...</code>, <code>host:port:secret</code>,
     <code>socks5://host:port</code>, or <code>direct</code>. The bot tries the active
     line first and rotates to the next on failure.</p>
  <textarea name="proxies" rows="8">{entries_text}</textarea>
  <p><label>Active line (0-based):
     <input type="number" name="active_index" min="0" value="{snapshot.active_index}"></label></p>
  <button type="submit">Save &amp; reconnect</button>
</form>
</body></html>
"""


def _make_handler(proxy_store: ProxyStore, username: str, password: str):
    failures = _FailureTracker()

    class AdminHandler(BaseHTTPRequestHandler):
        server_version = "proxyadmin/1.0"

        def _client_ip(self) -> str:
            return self.client_address[0] if self.client_address else "?"

        def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
            # Route through logging; never include the request body/query (secrets).
            logger.info("admin_web %s - %s", self._client_ip(), format % args)

        def _authorized(self) -> bool:
            header = self.headers.get("Authorization", "")
            if not header.startswith("Basic "):
                return False
            try:
                decoded = b64decode(header[6:]).decode("utf-8")
                got_user, _, got_pass = decoded.partition(":")
            except (ValueError, UnicodeDecodeError):
                return False
            user_ok = secrets.compare_digest(got_user, username)
            pass_ok = secrets.compare_digest(got_pass, password)
            return user_ok and pass_ok

        def _require_auth(self) -> bool:
            ip = self._client_ip()
            if failures.is_locked(ip):
                self.send_response(429)
                self.send_header("Retry-After", str(_LOCKOUT_WINDOW_SECONDS))
                self.end_headers()
                self.wfile.write(b"Too many failed attempts. Try again later.\n")
                return False
            if self._authorized():
                failures.clear(ip)
                return True
            failures.record_failure(ip)
            logger.warning("admin_web failed auth from %s", ip)
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Proxy admin"')
            self.end_headers()
            self.wfile.write(b"Unauthorized\n")
            return False

        def _send_html(self, body: str, status: int = 200) -> None:
            encoded = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:  # noqa: N802 - stdlib name
            if self.path.split("?", 1)[0] == "/healthz":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok\n")
                return
            if not self._require_auth():
                return
            self._send_html(_render_page(proxy_store))

        def do_POST(self) -> None:  # noqa: N802 - stdlib name
            if not self._require_auth():
                return
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw_body = self.rfile.read(length).decode("utf-8") if length else ""
            fields = parse_qs(raw_body, keep_blank_values=True)
            proxies_raw = fields.get("proxies", [""])[0]
            active_index_raw = fields.get("active_index", ["0"])[0]

            entries = proxies_raw.replace("\r\n", "\n").split("\n")
            try:
                active_index = int(active_index_raw)
            except ValueError:
                active_index = 0

            try:
                proxy_store.replace_all(entries, active_index=active_index)
            except ProxyError as exc:
                self._send_html(_render_page(proxy_store, message=f"Rejected: {exc}"), status=400)
                return

            reconnected = runtime.request_reconnect()
            note = "Saved. Reconnecting now." if reconnected else "Saved. Will apply on next connection."
            self._send_html(_render_page(proxy_store, message=note))

    return AdminHandler


def start_admin_web(proxy_store: ProxyStore, username: str, password: str, port: int) -> None:
    """Start the admin page in a daemon thread bound to all interfaces on ``port``."""
    handler = _make_handler(proxy_store, username, password)
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)

    thread = threading.Thread(
        target=server.serve_forever,
        name="proxy-admin-web",
        daemon=True,
    )
    thread.start()
    logger.info("Proxy admin web page listening on port %d", port)
