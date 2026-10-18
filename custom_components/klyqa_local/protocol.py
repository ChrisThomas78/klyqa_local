"""Local Klyqa (QCX) protocol.

The client broadcasts "QCX-SYN" on UDP 2222. The device then opens a TCP
connection back to the client on port 3333 and sends its identity in plain
JSON. Both sides exchange 8-byte IVs and continue with AES-128-CBC
(key from the Klyqa cloud, IV = sender IV + receiver IV), JSON padded
with spaces to 16 bytes. Every packet has a 4-byte header:
2 bytes length, 2 bytes type (0 ident, 1 IV, 2 encrypted payload).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .const import REQUEST_TIMEOUT, TCP_PORT, UDP_PORT

_LOGGER = logging.getLogger(__name__)


class KlyqaError(Exception):
    """Communication with a Klyqa device failed."""


async def _read_pkg(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    header = await reader.readexactly(4)
    length = int.from_bytes(header[:2], "big")
    pkg_type = int.from_bytes(header[2:], "big")
    return pkg_type, await reader.readexactly(length)


class KlyqaHub:
    """Shared UDP/TCP endpoints for all Klyqa devices of this HA instance."""

    def __init__(self) -> None:
        self._server: asyncio.Server | None = None
        self._udp: asyncio.DatagramTransport | None = None
        self._waiters: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    async def async_start(self) -> None:
        loop = asyncio.get_running_loop()
        self._server = await asyncio.start_server(
            self._on_connect, "0.0.0.0", TCP_PORT, reuse_address=True
        )
        self._udp, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol,
            local_addr=("0.0.0.0", UDP_PORT),
            allow_broadcast=True,
        )

    async def async_stop(self) -> None:
        if self._udp:
            self._udp.close()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _on_connect(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            pkg_type, body = await asyncio.wait_for(_read_pkg(reader), 5)
            ident = json.loads(body).get("ident", {}) if pkg_type == 0 else {}
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ValueError, OSError):
            writer.close()
            return
        unit_id = str(ident.get("unit_id", "")).upper()
        waiter = self._waiters.get(unit_id)
        if waiter is None or waiter.done():
            writer.close()
            return
        waiter.set_result((reader, writer, ident))

    async def async_request(
        self, unit_id: str, aes_key: bytes, message: dict[str, Any], host: str | None = None
    ) -> dict[str, Any]:
        """Send one JSON message to the device and return its JSON answer."""
        unit_id = unit_id.upper()
        loop = asyncio.get_running_loop()
        async with self._lock:
            waiter: asyncio.Future = loop.create_future()
            self._waiters[unit_id] = waiter
            try:
                deadline = loop.time() + REQUEST_TIMEOUT
                while not waiter.done():
                    if loop.time() > deadline:
                        raise KlyqaError(f"device {unit_id} did not connect back")
                    if self._udp:
                        if host:
                            self._udp.sendto(b"QCX-SYN", (host, UDP_PORT))
                        self._udp.sendto(b"QCX-SYN", ("255.255.255.255", UDP_PORT))
                    await asyncio.wait({waiter}, timeout=1)
                reader, writer, _ident = waiter.result()
            finally:
                self._waiters.pop(unit_id, None)

            try:
                return await asyncio.wait_for(
                    self._converse(reader, writer, aes_key, message), REQUEST_TIMEOUT
                )
            except (asyncio.TimeoutError, asyncio.IncompleteReadError, OSError, ValueError) as err:
                raise KlyqaError(f"communication with {unit_id} failed: {err!r}") from err
            finally:
                writer.close()

    @staticmethod
    async def _converse(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        aes_key: bytes,
        message: dict[str, Any],
    ) -> dict[str, Any]:
        local_iv = os.urandom(8)
        writer.write(bytes([0, 8, 0, 1]) + local_iv)
        await writer.drain()
        pkg_type, remote_iv = await _read_pkg(reader)
        if pkg_type != 1:
            raise ValueError(f"expected IV packet, got type {pkg_type}")

        encryptor = Cipher(algorithms.AES(aes_key), modes.CBC(local_iv + remote_iv)).encryptor()
        decryptor = Cipher(algorithms.AES(aes_key), modes.CBC(remote_iv + local_iv)).decryptor()

        plain = json.dumps(message).encode()
        plain += b" " * (-len(plain) % 16)
        cipher = encryptor.update(plain) + encryptor.finalize()
        writer.write(bytes([len(cipher) // 256, len(cipher) % 256, 0, 2]) + cipher)
        await writer.drain()

        while True:
            pkg_type, body = await _read_pkg(reader)
            if pkg_type == 2:
                break
        answer = decryptor.update(body).decode(errors="replace").strip(" \x00")
        _LOGGER.debug("Klyqa answer: %s", answer)
        return json.loads(answer)
