"""Proxy parsing and Telethon transport selection.

This is the single place that understands proxy strings. It is used by the proxy
store (config loading), the admin web page (validating pasted input), and the
``check_telegram`` diagnostics tool, so there is exactly one parser to keep correct.

Supported input forms (see :func:`parse_proxy`):

- ``tg://proxy?server=...&port=...&secret=...`` links
- ``https://t.me/proxy?server=...&port=...&secret=...`` links
- plain ``host:port:secret`` MTProxy triples
- ``socks5://[user:pass@]host:port`` SOCKS5 URLs
- the literal ``direct`` (or empty), meaning no proxy

MTProxy secrets come in three flavours, distinguished by their prefix once decoded:

- plain (16 raw bytes) and ``dd`` (random-padding) secrets are handled natively by
  Telethon's ``ConnectionTcpMTProxyRandomizedIntermediate``.
- ``ee`` (FakeTLS, domain-fronted) secrets are what ``mtg`` v2 emits today, and
  Telethon cannot speak them (it strips the domain and never does a TLS handshake).
  They route to our own FakeTLS connection class (Phase B). Until that lands, an
  ``ee`` secret fails loudly at startup rather than connecting and hanging.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

from telethon.network import ConnectionTcpMTProxyRandomizedIntermediate

_DIRECT_TOKENS = frozenset({"", "direct", "none", "off"})


class ProxyError(ValueError):
    """Raised when a proxy string cannot be parsed or is unsupported."""


@dataclass(frozen=True)
class Proxy:
    """A parsed, normalized proxy definition.

    ``kind`` is one of ``"direct"``, ``"mtproxy"`` or ``"socks5"``. ``raw`` keeps the
    original string so the proxy store and admin page can round-trip exactly what the
    user typed.
    """

    kind: str
    raw: str
    host: str | None = None
    port: int | None = None
    secret: str | None = None
    username: str | None = None
    password: str | None = None

    @property
    def is_direct(self) -> bool:
        return self.kind == "direct"

    @property
    def secret_kind(self) -> str | None:
        """``"plain"``, ``"dd"`` or ``"ee"`` for MTProxy; ``None`` otherwise."""
        if self.kind != "mtproxy" or self.secret is None:
            return None
        return classify_secret(self.secret)

    def describe(self) -> str:
        """Short, secret-free description safe to log and show in the UI."""
        if self.kind == "direct":
            return "direct (no proxy)"
        if self.kind == "mtproxy":
            return f"mtproxy {self.host}:{self.port} ({self.secret_kind})"
        auth = "auth " if self.username else ""
        return f"socks5 {auth}{self.host}:{self.port}"


def _decode_secret_bytes(secret: str) -> bytes:
    """Decode an MTProxy secret (hex or base64) to raw bytes, prefix included."""
    try:
        return bytes.fromhex(secret)
    except ValueError:
        padded = secret + "=" * (-len(secret) % 4)
        try:
            return base64.urlsafe_b64decode(padded.encode())
        except (binascii.Error, ValueError) as exc:
            raise ProxyError(f"Invalid MTProxy secret: {secret!r}") from exc


def classify_secret(secret: str) -> str:
    """Classify an MTProxy secret as ``"plain"``, ``"dd"`` or ``"ee"``.

    Works for both hex and base64 encodings: an ``ee``/``dd`` marker shows up either
    as a literal hex prefix or as a leading ``0xee``/``0xdd`` byte after decoding.
    """
    lowered = secret.strip().lower()
    # Hex form keeps the marker as literal leading characters.
    try:
        bytes.fromhex(lowered)
    except ValueError:
        pass
    else:
        if lowered.startswith("ee"):
            return "ee"
        if lowered.startswith("dd"):
            return "dd"
        return "plain"

    # Base64 form: inspect the first decoded byte.
    decoded = _decode_secret_bytes(secret)
    if not decoded:
        raise ProxyError(f"Empty MTProxy secret: {secret!r}")
    if decoded[0] == 0xEE:
        return "ee"
    if decoded[0] == 0xDD:
        return "dd"
    return "plain"


def _parse_int_port(raw: str, source: str) -> int:
    try:
        port = int(raw)
    except (TypeError, ValueError) as exc:
        raise ProxyError(f"Invalid port in {source}: {raw!r}") from exc
    if not (0 < port < 65536):
        raise ProxyError(f"Port out of range in {source}: {port}")
    return port


def _parse_mtproxy_link(raw: str) -> Proxy:
    parsed = urlparse(raw)
    query = parse_qs(parsed.query)

    def _single(name: str) -> str | None:
        values = query.get(name)
        return values[0] if values else None

    server = _single("server")
    port = _single("port")
    secret = _single("secret")
    if not server or not port or not secret:
        raise ProxyError(f"MTProxy link missing server/port/secret: {raw!r}")

    secret = unquote(secret).strip()
    # Validate the secret is decodable (and classifiable) up front.
    classify_secret(secret)
    return Proxy(
        kind="mtproxy",
        raw=raw,
        host=server.strip(),
        port=_parse_int_port(port, "MTProxy link"),
        secret=secret,
    )


def _parse_socks5_url(raw: str) -> Proxy:
    parsed = urlparse(raw)
    if not parsed.hostname or not parsed.port:
        raise ProxyError(f"SOCKS5 URL missing host/port: {raw!r}")
    return Proxy(
        kind="socks5",
        raw=raw,
        host=parsed.hostname,
        port=_parse_int_port(str(parsed.port), "SOCKS5 URL"),
        username=unquote(parsed.username) if parsed.username else None,
        password=unquote(parsed.password) if parsed.password else None,
    )


def _parse_host_port_secret(raw: str) -> Proxy:
    parts = raw.split(":")
    if len(parts) != 3:
        raise ProxyError(
            f"Unrecognized proxy string: {raw!r}. Expected a tg://proxy link, a "
            "socks5:// URL, or host:port:secret."
        )
    host, port, secret = (part.strip() for part in parts)
    if not host or not secret:
        raise ProxyError(f"host:port:secret has empty host or secret: {raw!r}")
    classify_secret(secret)
    return Proxy(
        kind="mtproxy",
        raw=raw,
        host=host,
        port=_parse_int_port(port, "host:port:secret"),
        secret=secret,
    )


def parse_proxy(raw: str) -> Proxy:
    """Parse one proxy definition. Raises :class:`ProxyError` on malformed input."""
    text = (raw or "").strip()
    if text.lower() in _DIRECT_TOKENS:
        return Proxy(kind="direct", raw=text)

    lowered = text.lower()
    if lowered.startswith("tg://proxy") or "t.me/proxy" in lowered:
        return _parse_mtproxy_link(text)
    if lowered.startswith(("socks5://", "socks5h://")):
        return _parse_socks5_url(text)
    return _parse_host_port_secret(text)


def build_connection_kwargs(proxy: Proxy | None) -> dict:
    """Return the ``TelegramClient`` kwargs (``connection`` / ``proxy``) for a proxy.

    ``None`` or a direct proxy yields ``{}`` (Telethon connects directly). Note the
    MTProxy ``proxy`` value must be a **tuple** ``(host, port, secret)`` — Telethon's
    ``address_info()`` slices ``proxy_info[:2]``; the dict form is only for SOCKS/HTTP.
    """
    if proxy is None or proxy.is_direct:
        return {}

    if proxy.kind == "socks5":
        socks: dict = {
            "proxy_type": "socks5",
            "addr": proxy.host,
            "port": proxy.port,
            "rdns": True,
        }
        if proxy.username:
            socks["username"] = proxy.username
            socks["password"] = proxy.password or ""
        return {"proxy": socks}

    if proxy.kind == "mtproxy":
        assert proxy.secret is not None
        secret_kind = classify_secret(proxy.secret)
        if secret_kind == "ee":
            # FakeTLS. Handled by our own connection class in Phase B.
            connection = _resolve_faketls_connection()
        else:
            connection = ConnectionTcpMTProxyRandomizedIntermediate
        return {
            "connection": connection,
            "proxy": (proxy.host, proxy.port, proxy.secret),
        }

    raise ProxyError(f"Unsupported proxy kind: {proxy.kind}")


def _resolve_faketls_connection():
    """Return the FakeTLS connection class, or fail loudly if it is unavailable.

    Kept as a lazy import so Phase A works without the Phase B module present. When
    ``faketls`` is missing, an ``ee`` secret raises a clear error at startup instead
    of silently connecting through Telethon (which drops the domain and hangs).
    """
    try:
        from .faketls import ConnectionTcpMTProxyFakeTLS
    except ImportError as exc:  # pragma: no cover - exercised only before Phase B
        raise ProxyError(
            "This proxy uses a FakeTLS ('ee') secret, which requires the FakeTLS "
            "transport (app/bot/faketls.py). It is not available in this build. Use a "
            "plain or 'dd' MTProxy secret, or a socks5:// proxy, instead."
        ) from exc
    return ConnectionTcpMTProxyFakeTLS
