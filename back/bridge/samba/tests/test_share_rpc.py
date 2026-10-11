"""Synthetic malformed responses and fragmented SRVSVC transport contracts."""
import struct

import pytest

from bridge.samba.share_rpc import ShareEnumerationError, _Channel, _decode


def _stub():
    # A level-1 response with a Unicode disk share and a null comment pointer.
    name = "équipe\0".encode("utf-16-le")
    string = struct.pack("<III", len(name) // 2, 0, len(name) // 2) + name
    string += b"\0" * ((-len(name)) % 4)
    return (struct.pack("<IIIIIIIII", 1, 1, 0x20000, 1, 0x20004, 1, 0x20008, 0, 0)
            + string + struct.pack("<IIII", 1, 0x2000C, 0, 0))


@pytest.mark.parametrize("chunk_size", [1, 17, 512])
def test_rpc_fragments_and_short_pipe_reads_preserve_unicode_share(chunk_size):
    stub = _stub()
    packets = bytearray()
    for index, fragment in enumerate((stub[:21], stub[21:])):
        body = struct.pack("<IHBB", len(stub), 0, 0, 0) + fragment
        packets.extend(struct.pack("<BBBB4sHHI", 5, 0, 2, 1 if index == 0 else 2,
                                   b"\x10\0\0\0", len(body) + 16, 0, 2) + body)

    class Pipe:
        def write(self, data):
            return min(len(data), 3)

        def read(self, size):
            data = bytes(packets[:min(size, chunk_size)])
            del packets[:len(data)]
            return data

    response = _Channel(Pipe()).exchange(2, 0, b"synthetic request", 2)
    shares, resume = _decode(response)
    assert [(share.name, share.kind) for share in shares] == [("équipe", 0)]
    assert resume is None


def test_truncated_and_oversized_share_responses_fail_safely():
    response = _stub()
    for length in range(len(response)):
        with pytest.raises(OSError):
            _decode(response[:length])
    oversized = struct.pack("<IIII", 1, 1, 0x20000, 10_001) + b"\0" * 20
    with pytest.raises(ShareEnumerationError):
        _decode(oversized)
    with pytest.raises(PermissionError):
        _decode(struct.pack("<I", 5))
