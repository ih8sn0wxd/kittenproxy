import struct

CONNECT   = 0x01
CONNECTED = 0x02
DATA      = 0x03
CLOSE     = 0x04
ERROR     = 0x05

HEADER_SIZE = 5
MAX_PAYLOAD = 65536 - HEADER_SIZE


def pack(frame_type: int, stream_id: int, payload: bytes = b"") -> bytes:
    return struct.pack("!BI", frame_type, stream_id) + payload


def unpack(data: bytes) -> tuple[int, int, bytes]:
    frame_type, stream_id = struct.unpack("!BI", data[:HEADER_SIZE])
    
    return frame_type, stream_id, data[HEADER_SIZE:]


def pack_connect(stream_id: int, host: str, port: int) -> bytes:
    host_bytes: bytes = host.encode()
    addr_payload: bytes = struct.pack("!B", 0x03) + struct.pack("!B", len(host_bytes)) + host_bytes + struct.pack("!H", port)
    
    return pack(CONNECT, stream_id, addr_payload)


def unpack_connect(payload: bytes) -> tuple[str, int]:
    addr_type = payload[0]

    if (addr_type == 0x01):
        host = ".".join(str(b) for b in payload[1:5])
        port = struct.unpack("!H", payload[5:7])[0]
    elif (addr_type == 0x03):
        length = payload[1]
        host = payload[2:2 + length].decode()
        port = struct.unpack("!H", payload[2 + length:4 + length])[0]
    elif (addr_type == 0x04):
        parts = struct.unpack("!8H", payload[1:17])
        host = ":".join(f"{p:x}" for p in parts)
        port = struct.unpack("!H", payload[17:19])[0]

    return host, port
