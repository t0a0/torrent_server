"""FakeTLS ('ee' secret) MTProto proxy transport for Telethon.

Telethon's built-in MTProxy connection drops the domain from an ``ee`` secret and never
performs a TLS handshake, so it cannot talk to a FakeTLS proxy (``mtg`` v2, the standard
server today, emits only ``ee`` secrets). This module adds that missing handshake as a
Telethon connection class, so ``ee`` proxies work with the same client code as plain and
``dd`` proxies.

The FakeTLS scheme wraps the ordinary MTProxy (obfuscated2) stream inside TLS 1.3-looking
records so it is indistinguishable from HTTPS to a passive observer:

1. The client sends a browser-shaped TLS ClientHello whose 32-byte ``random`` field holds
   ``HMAC-SHA256(secret, ClientHello-with-random-zeroed)``, with the last 4 bytes XORed
   against the current Unix time. The proxy authenticates the client by recomputing it.
2. The proxy replies with a ServerHello + ChangeCipherSpec + one application-data record
   (a fake certificate). The client consumes those and the handshake is done.
3. Thereafter both sides exchange the real MTProto stream inside ``0x17 0x03 0x03`` TLS
   application-data records.

Protocol reference: ``alexbers/mtprotoproxy`` (server side; the client is its mirror).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import time

from telethon.network.connection.tcpintermediate import RandomizedIntermediatePacketCodec
from telethon.network.connection.tcpmtproxy import TcpMTProxy

_TLS_RECORD_HANDSHAKE = 0x16
_TLS_RECORD_CHANGE_CIPHER = 0x14
_TLS_RECORD_APP_DATA = 0x17
_TLS_VERSION = b"\x03\x03"
_DIGEST_LEN = 32
_DIGEST_POS = 11  # record header (5) + handshake type (1) + length (3) + version (2)
_MIN_CLIENT_HELLO = 517
_MAX_APP_DATA_CHUNK = 16384


def _u16(value: int) -> bytes:
    return value.to_bytes(2, "big")


def _u24(value: int) -> bytes:
    return value.to_bytes(3, "big")


def parse_ee_secret(secret: str) -> tuple[bytes, str]:
    """Split an ``ee`` FakeTLS secret into its 16-byte key and SNI domain.

    Accepts both hex (``ee`` + 32 hex chars + hex-encoded domain) and base64 (leading
    ``0xee`` byte + 16 key bytes + domain bytes) encodings.
    """
    text = secret.strip()
    try:
        raw = bytes.fromhex(text)
    except ValueError:
        padded = text + "=" * (-len(text) % 4)
        raw = base64.urlsafe_b64decode(padded.encode())

    if not raw or raw[0] != 0xEE:
        raise ValueError("Not a FakeTLS ('ee') secret")
    body = raw[1:]
    if len(body) < 16:
        raise ValueError("FakeTLS secret too short for a 16-byte key")
    key = body[:16]
    domain = body[16:].decode("utf-8", errors="strict") if len(body) > 16 else ""
    if not domain:
        raise ValueError("FakeTLS secret is missing its domain")
    return key, domain


def _sni_extension(domain: str) -> bytes:
    host = domain.encode()
    name_entry = b"\x00" + _u16(len(host)) + host  # host_name(0) + length + host
    name_list = _u16(len(name_entry)) + name_entry
    return b"\x00\x00" + _u16(len(name_list)) + name_list  # extension type server_name


def _build_client_hello(secret: bytes, domain: str) -> bytes:
    """Build a complete, HMAC-authenticated ClientHello record for the FakeTLS proxy."""
    session_id = os.urandom(32)
    key_share_key = os.urandom(32)

    cipher_suites = bytes.fromhex(
        "1301"  # TLS_AES_128_GCM_SHA256
        "1302"  # TLS_AES_256_GCM_SHA384
        "1303"  # TLS_CHACHA20_POLY1305_SHA256
        "c02b"  # ECDHE-ECDSA-AES128-GCM-SHA256
        "c02f"  # ECDHE-RSA-AES128-GCM-SHA256
        "c02c"  # ECDHE-ECDSA-AES256-GCM-SHA384
        "c030"  # ECDHE-RSA-AES256-GCM-SHA384
        "cca9"  # ECDHE-ECDSA-CHACHA20-POLY1305
        "cca8"  # ECDHE-RSA-CHACHA20-POLY1305
        "00ff"  # TLS_EMPTY_RENEGOTIATION_INFO_SCSV
    )

    supported_versions = b"\x00\x2b" + _u16(3) + b"\x02" + b"\x03\x04"  # TLS 1.3
    supported_groups = b"\x00\x0a" + _u16(4) + _u16(2) + b"\x00\x1d"  # x25519
    ec_point_formats = b"\x00\x0b" + _u16(2) + b"\x01\x00"
    sig_algs = b"\x00\x0d" + _u16(8) + _u16(6) + bytes.fromhex("0403080407040805")
    key_share = (
        b"\x00\x33"
        + _u16(len(b"\x00\x1d" + _u16(32) + key_share_key) + 2)
        + _u16(len(b"\x00\x1d" + _u16(32) + key_share_key))
        + b"\x00\x1d"
        + _u16(32)
        + key_share_key
    )

    extensions = (
        _sni_extension(domain)
        + supported_versions
        + supported_groups
        + ec_point_formats
        + sig_algs
        + key_share
    )

    def _assemble(padding_len: int) -> bytes:
        exts = extensions
        if padding_len > 0:
            exts = exts + b"\x00\x15" + _u16(padding_len) + b"\x00" * padding_len
        body = (
            _TLS_VERSION
            + b"\x00" * _DIGEST_LEN  # random placeholder (holds the digest)
            + bytes([len(session_id)])
            + session_id
            + _u16(len(cipher_suites))
            + cipher_suites
            + b"\x01\x00"  # compression: null
            + _u16(len(exts))
            + exts
        )
        handshake = b"\x01" + _u24(len(body)) + body
        return b"\x16" + b"\x03\x01" + _u16(len(handshake)) + handshake

    record = _assemble(0)
    if len(record) < _MIN_CLIENT_HELLO:
        # Add a padding extension so the ClientHello reaches a realistic browser size.
        needed = _MIN_CLIENT_HELLO - len(record) - 4  # 4 = padding extension header
        record = _assemble(max(needed, 0))

    # Authenticate: HMAC over the full record with the random field zeroed, then patch it
    # back in with the low 4 bytes XORed against the current time.
    zeroed = record[:_DIGEST_POS] + b"\x00" * _DIGEST_LEN + record[_DIGEST_POS + _DIGEST_LEN:]
    digest = bytearray(hmac.new(secret, zeroed, hashlib.sha256).digest())
    timestamp = int(time.time()).to_bytes(4, "little")
    for i in range(4):
        digest[28 + i] ^= timestamp[i]
    return record[:_DIGEST_POS] + bytes(digest) + record[_DIGEST_POS + _DIGEST_LEN:]


async def _read_tls_record(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    header = await reader.readexactly(5)
    record_type = header[0]
    length = int.from_bytes(header[3:5], "big")
    payload = await reader.readexactly(length) if length else b""
    return record_type, payload


async def _consume_server_handshake(reader: asyncio.StreamReader) -> None:
    """Read and discard the proxy's ServerHello + ChangeCipherSpec + first app-data record.

    After the first application-data record, the real MTProto stream begins.
    """
    for _ in range(8):  # generous cap; a well-behaved proxy uses 3 records
        record_type, _payload = await _read_tls_record(reader)
        if record_type == _TLS_RECORD_APP_DATA:
            return
        if record_type not in (_TLS_RECORD_HANDSHAKE, _TLS_RECORD_CHANGE_CIPHER):
            raise ConnectionError(f"Unexpected TLS record type during handshake: {record_type:#x}")
    raise ConnectionError("Proxy did not complete the FakeTLS handshake")


class _FakeTLSReader:
    """Presents the inner MTProto stream, unwrapping incoming TLS application-data records."""

    def __init__(self, raw: asyncio.StreamReader) -> None:
        self._raw = raw
        self._buffer = bytearray()

    async def readexactly(self, n: int) -> bytes:
        while len(self._buffer) < n:
            record_type, payload = await _read_tls_record(self._raw)
            if record_type == _TLS_RECORD_APP_DATA:
                self._buffer.extend(payload)
            # Ignore any post-handshake ChangeCipherSpec/handshake records.
        data = bytes(self._buffer[:n])
        del self._buffer[:n]
        return data

    def at_eof(self) -> bool:
        return not self._buffer and self._raw.at_eof()


class _FakeTLSWriter:
    """Frames the inner MTProto stream into outgoing TLS application-data records."""

    def __init__(self, raw: asyncio.StreamWriter) -> None:
        self._raw = raw

    def write(self, data: bytes) -> None:
        for start in range(0, len(data), _MAX_APP_DATA_CHUNK):
            chunk = data[start:start + _MAX_APP_DATA_CHUNK]
            self._raw.write(b"\x17" + _TLS_VERSION + _u16(len(chunk)) + chunk)

    async def drain(self) -> None:
        await self._raw.drain()

    def close(self) -> None:
        self._raw.close()

    async def wait_closed(self) -> None:
        await self._raw.wait_closed()


class ConnectionTcpMTProxyFakeTLS(TcpMTProxy):
    """MTProxy connection over a FakeTLS ('ee' secret) proxy.

    Reuses the randomized-intermediate codec that ``dd``/plain MTProxies use; the only
    difference is the TLS record wrapper interposed around the raw socket.
    """

    packet_codec = RandomizedIntermediatePacketCodec

    def __init__(self, ip, port, dc_id, *, loggers, proxy=None, local_addr=None):
        # Capture the FakeTLS key + domain before the base class discards the domain.
        self._tls_secret, self._tls_domain = parse_ee_secret(proxy[2])
        super().__init__(ip, port, dc_id, loggers=loggers, proxy=proxy, local_addr=local_addr)

    async def _connect(self, timeout=None, ssl=None):
        raw_reader, raw_writer = await asyncio.wait_for(
            asyncio.open_connection(host=self._ip, port=self._port),
            timeout=timeout,
        )

        # TLS handshake: send the authenticated ClientHello, consume the server's reply.
        raw_writer.write(_build_client_hello(self._tls_secret, self._tls_domain))
        await raw_writer.drain()
        await _consume_server_handshake(raw_reader)

        # From here the inner MTProto stream rides inside application-data records.
        self._reader = _FakeTLSReader(raw_reader)
        self._writer = _FakeTLSWriter(raw_writer)

        self._codec = self.packet_codec(self)
        self._init_conn()
        await self._writer.drain()

        # Same guard TcpMTProxy uses: if the codec/secret is wrong the proxy drops us
        # shortly after the initial payload.
        try:
            await asyncio.wait_for(raw_reader._wait_for_data("faketls"), 2)
        except asyncio.TimeoutError:
            pass
        except Exception:
            await asyncio.sleep(2)

        if self._reader.at_eof():
            await self.disconnect()
            raise ConnectionError("Proxy closed the connection after sending initial payload")
