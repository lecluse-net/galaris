"""Bounded SRVSVC share enumeration over an authenticated SMB named pipe.

Wire structures adapted from Jordan Borean's smb_list_shares.py (2024), MIT:
https://gist.github.com/jborean93/13dbfbd94e83ff810afc55e178371eb9
See SHARE_RPC_LICENSE. MS-SRVS NetrShareEnum (opnum 15), NDR32 only.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import BinaryIO
from uuid import UUID

MAX_SHARES = 10_000
_MAX_BYTES = 8 * 1024 * 1024
_NDR = UUID("8a885d04-1ceb-11c9-9fe8-08002b104860").bytes_le
_SRVSVC = UUID("4b324fc8-1670-01d3-1278-5a47bf6ee188").bytes_le


class ShareEnumerationError(OSError):
    """Safe error for malformed or unsupported share enumeration responses."""


@dataclass(frozen=True)
class ShareInfo:
    name: str
    kind: int


def _invalid() -> ShareEnumerationError:
    return ShareEnumerationError("The server returned an invalid or oversized share listing.")


def _packet(call: int, kind: int, body: bytes) -> bytes:
    return struct.pack("<BBBB4sHHI", 5, 0, kind, 3, b"\x10\0\0\0", len(body) + 16, 0, call) + body


class _Channel:
    def __init__(self, pipe: BinaryIO) -> None:
        self.pipe = pipe
        self.buffer = bytearray()
        self.received = 0

    def exchange(self, call: int, kind: int, body: bytes, expected_kind: int) -> bytes:
        request = memoryview(_packet(call, kind, body))
        while request:
            written = self.pipe.write(request)
            if not written:
                raise _invalid()
            request = request[written:]
        result = bytearray()
        first = True
        while True:
            while len(self.buffer) < 16:
                self._receive()
            major, minor, packet_kind, flags, representation, length, auth, packet_call = struct.unpack(
                "<BBBB4sHHI", self.buffer[:16]
            )
            if (major != 5 or minor != 0 or representation != b"\x10\0\0\0"
                or auth or packet_call != call or length < 16
                or bool(flags & 1) != first):
                raise _invalid()
            while len(self.buffer) < length:
                self._receive()
            payload = bytes(self.buffer[16:length])
            del self.buffer[:length]
            if packet_kind == 3:
                raise ShareEnumerationError("The server refused share discovery via SRVSVC.")
            if packet_kind != expected_kind:
                raise _invalid()
            if packet_kind == 2:
                if len(payload) < 8 or struct.unpack_from("<H", payload, 4)[0] != 0:
                    raise _invalid()
                payload = payload[8:]
            result.extend(payload)
            if len(result) > _MAX_BYTES:
                raise _invalid()
            if flags & 2:
                return bytes(result)
            first = False

    def _receive(self) -> None:
        block = self.pipe.read(65_535)
        self.received += len(block)
        if not block or self.received > _MAX_BYTES:
            raise _invalid()
        self.buffer.extend(block)


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def take(self, length: int) -> bytes:
        if length < 0 or self.offset + length > len(self.data):
            raise _invalid()
        value = self.data[self.offset:self.offset + length]
        self.offset += length
        return value

    def integer(self) -> int:
        self.align()
        return struct.unpack("<I", self.take(4))[0]

    def align(self) -> None:
        self.take((-self.offset) % 4)

    def string(self) -> str:
        maximum, offset, count = self.integer(), self.integer(), self.integer()
        if offset or not 1 <= count <= maximum <= 32_768:
            raise _invalid()
        raw = self.take(count * 2)
        if raw[-2:] != b"\0\0":
            raise _invalid()
        try:
            value = raw[:-2].decode("utf-16-le")
        except UnicodeError:
            raise _invalid() from None
        self.align()
        return value


def _decode(data: bytes) -> tuple[list[ShareInfo], int | None]:
    if len(data) < 4:
        raise _invalid()
    status = struct.unpack_from("<I", data, len(data) - 4)[0]
    if status == 5:
        raise PermissionError("The server denied share discovery for this account.")
    if status not in {0, 234}:
        raise ShareEnumerationError("The server refused share discovery via SRVSVC.")
    reader = _Reader(data)
    if reader.integer() != 1 or reader.integer() != 1 or not reader.integer():
        raise _invalid()
    count, pointer = reader.integer(), reader.integer()
    if count > MAX_SHARES or (count and not pointer):
        raise _invalid()
    if pointer and reader.integer() != count:
        raise _invalid()
    headers = [(reader.integer(), reader.integer(), reader.integer()) for _ in range(count)]
    shares: list[ShareInfo] = []
    for name_pointer, kind, comment_pointer in headers:
        if not name_pointer:
            raise _invalid()
        name = reader.string()
        if comment_pointer:
            reader.string()
        shares.append(ShareInfo(name, kind))
    reader.integer()  # TotalEntries, not an allocation limit.
    resume = reader.integer() if reader.integer() else None
    if reader.integer() != status or reader.offset != len(data) or (status == 234 and resume is None):
        raise _invalid()
    return shares, resume if status == 234 else None


def list_shares(pipe: BinaryIO, server: str) -> list[ShareInfo]:
    channel = _Channel(pipe)
    context = struct.pack("<HBB", 0, 1, 0) + _SRVSVC + struct.pack("<I", 3) + _NDR + struct.pack("<I", 2)
    acknowledgement = channel.exchange(1, 11, struct.pack("<HHI", 4280, 4280, 0) + b"\x01\0\0\0" + context, 12)
    if len(acknowledgement) < 10:
        raise _invalid()
    address_length = struct.unpack_from("<H", acknowledgement, 8)[0]
    result_offset = (10 + address_length + 3) & ~3
    result = acknowledgement[result_offset:]
    if (len(result) != 28 or result[:4] != b"\x01\0\0\0"
        or struct.unpack_from("<H", result, 4)[0] != 0
        or result[8:24] != _NDR or struct.unpack_from("<I", result, 24)[0] != 2):
        raise ShareEnumerationError("The server does not support share discovery via SRVSVC/NDR32.")
    name = ("\\\\" + server + "\0").encode("utf-16-le")
    count = len(name) // 2
    server_data = struct.pack("<IIII", 0x20000, count, 0, count) + name + b"\0" * ((-len(name)) % 4)
    shares: list[ShareInfo] = []
    seen_resumes: set[int] = {0}
    resume = 0
    for call in range(2, 514):
        # Level 1, empty input container, bounded preferred page size, resume pointer.
        stub = server_data + struct.pack("<IIIIIIII", 1, 1, 0x20004, 0, 0, 32_768, 0x20008, resume)
        response = channel.exchange(call, 0, struct.pack("<IHH", len(stub), 0, 15) + stub, 2)
        entries, next_resume = _decode(response)
        shares.extend(entries)
        if len(shares) > MAX_SHARES:
            raise _invalid()
        if next_resume is None:
            return shares
        if next_resume in seen_resumes:
            raise _invalid()
        seen_resumes.add(next_resume)
        resume = next_resume
    raise _invalid()
