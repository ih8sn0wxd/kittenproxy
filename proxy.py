import asyncio
from loguru import logger
from util import protocol
from config import PROXY_CONF

SOCKS_VERSION = 0x05
NO_AUTH = 0x00
CMD_CONNECT = 0x01
ATYP_IPV4 = 0x01
ATYP_DOMAIN = 0x03
ATYP_IPV6 = 0x04

class SocksProxy:
    def __init__(self, host: str = PROXY_CONF["host"], port: int = PROXY_CONF["port"]):
        self.host = host
        self.port = port
        self._stream_counter: int = 0
        self._streams: dict[int, asyncio.StreamWriter] = {}
        self._connect_events: dict[int, asyncio.Event] = {}
        self._connect_results: dict[int, bool] = {}
        self._send_frame = None
        self._server = None

    def bind(self, send_frame):
        self._send_frame = send_frame

    async def start(self):
        self._server = await asyncio.start_server(self._handle_client, self.host, self.port)
        logger.success(f"[SOCKS5]: Listening on {self.host}:{self.port}")

    async def stop(self):
        if (self._server):
            self._server.close()
            await self._server.wait_closed()

        for writer in self._streams.values():
            writer.close()

    def on_frame(self, frame_type: int, stream_id: int, payload: bytes):
        if (frame_type == protocol.CONNECTED):
            self._connect_results[stream_id] = True
            ev = self._connect_events.get(stream_id)
            
            if (ev):
                ev.set()

        elif (frame_type == protocol.DATA):
            writer = self._streams.get(stream_id)
            
            if (writer and not writer.is_closing()):
                writer.write(payload)

        elif (frame_type == protocol.CLOSE or frame_type == protocol.ERROR):
            if (frame_type == protocol.ERROR):
                self._connect_results[stream_id] = False
                ev = self._connect_events.get(stream_id)
                
                if (ev):
                    ev.set()

            writer = self._streams.pop(stream_id, None)

            if (writer and not writer.is_closing()):
                writer.close()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            await self._do_handshake(reader, writer)
        except Exception as e:
            logger.debug(f"[SOCKS5]: Handshake failed: {e}")
            writer.close()

    async def _do_handshake(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        # greeting

        header = await reader.readexactly(2)

        if (header[0] != SOCKS_VERSION):
            writer.close()

            return

        nmethods = header[1]
        methods = await reader.readexactly(nmethods)

        if (NO_AUTH not in methods):
            writer.write(bytes([SOCKS_VERSION, 0xFF]))
            await writer.drain()
            writer.close()

            return

        writer.write(bytes([SOCKS_VERSION, NO_AUTH]))
        await writer.drain()

        # request
        req = await reader.readexactly(4)

        if (req[0] != SOCKS_VERSION or req[1] != CMD_CONNECT):
            writer.write(bytes([SOCKS_VERSION, 0x07, 0x00, ATYP_IPV4, 0, 0, 0, 0, 0, 0]))
            
            await writer.drain()
            writer.close()

            return

        atyp = req[3]

        if (atyp == ATYP_IPV4):
            raw = await reader.readexactly(4)
            host = ".".join(str(b) for b in raw)
        elif (atyp == ATYP_DOMAIN):
            length = (await reader.readexactly(1))[0]
            host = (await reader.readexactly(length)).decode()
        elif (atyp == ATYP_IPV6):
            raw = await reader.readexactly(16)
            import struct
            parts = struct.unpack("!8H", raw)
            host = ":".join(f"{p:x}" for p in parts)
        else:
            writer.write(bytes([SOCKS_VERSION, 0x08, 0x00, ATYP_IPV4, 0, 0, 0, 0, 0, 0]))
            await writer.drain()
            writer.close()

            return

        port_raw = await reader.readexactly(2)
        port = int.from_bytes(port_raw, "big")

        # allocate stream
        self._stream_counter += 1
        stream_id = self._stream_counter

        self._streams[stream_id] = writer
        self._connect_events[stream_id] = asyncio.Event()
        self._connect_results[stream_id] = False

        logger.info(f"[SOCKS5]: #{stream_id} CONNECT {host}:{port}")

        self._send_frame(protocol.pack_connect(stream_id, host, port))

        try:
            await asyncio.wait_for(self._connect_events[stream_id].wait(), timeout=10)
        except asyncio.TimeoutError:
            logger.warning(f"[SOCKS5]: #{stream_id} connect timeout")
            writer.write(bytes([SOCKS_VERSION, 0x04, 0x00, ATYP_IPV4, 0, 0, 0, 0, 0, 0]))
            await writer.drain()
            self._streams.pop(stream_id, None)
            writer.close()
            return
        finally:
            self._connect_events.pop(stream_id, None)

        if (not self._connect_results.pop(stream_id, False)):
            logger.warning(f"[SOCKS5]: #{stream_id} remote refused")
            
            writer.write(bytes([SOCKS_VERSION, 0x05, 0x00, ATYP_IPV4, 0, 0, 0, 0, 0, 0]))
            await writer.drain()
            self._streams.pop(stream_id, None)
            writer.close()

            return

        # success reply: bind to 0.0.0.0:0
        writer.write(bytes([SOCKS_VERSION, 0x00, 0x00, ATYP_IPV4, 0, 0, 0, 0, 0, 0]))
        await writer.drain()

        logger.success(f"[SOCKS5]: #{stream_id} connected → relay")

        # pump TCP → DC
        try:
            while True:
                data = await reader.read(protocol.MAX_PAYLOAD)
                if (not data):
                    break

                self._send_frame(protocol.pack(protocol.DATA, stream_id, data))
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self._streams.pop(stream_id, None)
            self._send_frame(protocol.pack(protocol.CLOSE, stream_id))
            writer.close()
            
            logger.debug(f"[SOCKS5]: #{stream_id} closed")
