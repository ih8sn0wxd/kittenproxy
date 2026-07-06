import asyncio
from loguru import logger
from util import protocol


class Relay:
    def __init__(self):
        self._streams: dict[int, tuple[asyncio.StreamReader, asyncio.StreamWriter]] = {}
        self._tasks: dict[int, asyncio.Task] = {}
        self._send_frame = None

    def bind(self, send_frame):
        self._send_frame = send_frame

    def on_frame(self, frame_type: int, stream_id: int, payload: bytes):
        if (frame_type == protocol.CONNECT):
            host, port = protocol.unpack_connect(payload)
            asyncio.ensure_future(self._do_connect(stream_id, host, port))

        elif (frame_type == protocol.DATA):
            pair = self._streams.get(stream_id)
            if (pair):
                _, writer = pair
                if (not writer.is_closing()):
                    writer.write(payload)

        elif (frame_type == protocol.CLOSE):
            self._close_stream(stream_id)

    async def _do_connect(self, stream_id: int, host: str, port: int):
        logger.info(f"[Relay]: #{stream_id} connecting to {host}:{port}")

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=10
            )
        except Exception as e:
            logger.warning(f"[Relay]: #{stream_id} connect failed: {e}")
            self._send_frame(protocol.pack(protocol.ERROR, stream_id, b"\x01"))
            
            return

        self._streams[stream_id] = (reader, writer)
        self._send_frame(protocol.pack(protocol.CONNECTED, stream_id))

        logger.success(f"[Relay]: #{stream_id} connected → {host}:{port}")

        self._tasks[stream_id] = asyncio.ensure_future(self._pump(stream_id, reader))

    async def _pump(self, stream_id: int, reader: asyncio.StreamReader):
        try:
            while True:
                data = await reader.read(protocol.MAX_PAYLOAD)

                if (not data):
                    break

                self._send_frame(protocol.pack(protocol.DATA, stream_id, data))
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self._close_stream(stream_id)
            self._send_frame(protocol.pack(protocol.CLOSE, stream_id))
            
            logger.debug(f"[Relay]: #{stream_id} closed")

    def _close_stream(self, stream_id: int):
        task = self._tasks.pop(stream_id, None)

        if (task and not task.done()):
            task.cancel()

        pair = self._streams.pop(stream_id, None)
        
        if (pair):
            _, writer = pair
            
            if (not writer.is_closing()):
                writer.close()

    async def stop(self):
        for sid in list(self._streams):
            self._close_stream(sid)
