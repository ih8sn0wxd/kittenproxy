import asyncio
from aiortc import RTCPeerConnection, RTCConfiguration, RTCIceServer, RTCSessionDescription, RTCIceCandidate
from aiortc.contrib.media import MediaPlayer
from loguru import logger

RESERVED_PING: str = "ping"
RESERVED_PONG: str = "pong"
KEEPALIVE_INTERVAL: int = 5
KEEPALIVE_TIMEOUT: int = 10


class RtcPeer:
    def __init__(self, stun: dict, turn: dict):
        ice_servers: list = [
            RTCIceServer(urls = stun["urls"]),
            RTCIceServer(urls = turn["urls"], username = turn["username"], credential = turn["credential"]),
        ]

        self.pc = RTCPeerConnection(configuration=RTCConfiguration(iceServers = ice_servers))
        self.channels: dict[str, object] = {}
        self.on_binary = None
        self.on_connected = None
        self.on_timeout = None
        self._keepalive_task: asyncio.Task | None = None
        self._got_pong: bool = False

        self._player = MediaPlayer("anullsrc=r=48000:cl=stereo", format = "lavfi")
        self.pc.addTrack(self._player.audio)

        self._setup_pc_events()

    def _setup_pc_events(self):
        @self.pc.on("iceconnectionstatechange")
        async def on_ice_state():
            logger.info(f"[ICE]: State is {self.pc.iceConnectionState}")

        @self.pc.on("connectionstatechange")
        async def on_conn_state():
            logger.info(f"[Connection]: State is {self.pc.connectionState}")

            if (self.pc.connectionState == "connected"):
                logger.success("\n\n== KittenProxy connection is ready! ==\n")
                if self.on_connected:
                    self.on_connected()
                self._keepalive_task = asyncio.ensure_future(self._keepalive_loop())

            if (self.pc.connectionState in ("failed", "disconnected", "closed")):
                logger.warning(f"[Connection]: Lost connection ({self.pc.connectionState})")
                if self.on_timeout:
                    self.on_timeout()

        @self.pc.on("datachannel")
        def on_remote_datachannel(channel):
            logger.info(f"remote datachannel: {channel.label}")

            self._bind_channel(channel.label, channel)

    def add_channel(self, name: str):
        ch = self.pc.createDataChannel(name)

        self._bind_channel(name, ch)

    def _bind_channel(self, name: str, ch):
        self.channels[name] = ch

        @ch.on("open")
        def on_open():
            logger.success(f"[RTC Peer]: on_open invoked. DC = {name}")

            ch.send(RESERVED_PING) # Greeting message

        @ch.on("message")
        def on_message(msg):
            if (isinstance(msg, bytes)):
                if self.on_binary:
                    self.on_binary(msg)
            else:
                if (msg == RESERVED_PING):
                    logger.debug(f"[DataChannel]: Received ping. DC = {name}")

                    ch.send(RESERVED_PONG)
                if (msg == RESERVED_PONG):
                    logger.debug(f"[DataChannel]: Pong. DC = {name}")
                    self._got_pong = True

        @ch.on("close")
        def on_close():
            logger.info(f"[DataChannel]: Closed")

    async def _keepalive_loop(self):
        import config
        ch_name = config.TARGET_DATACHANNEL

        await asyncio.sleep(KEEPALIVE_INTERVAL)

        while True:
            ch = self.channels.get(ch_name)

            if (not ch or ch.readyState != "open"):
                break

            self._got_pong = False
            ch.send(RESERVED_PING)

            await asyncio.sleep(KEEPALIVE_TIMEOUT)

            if (not self._got_pong):
                logger.error("[Keepalive]: No pong received within timeout")
                if self.on_timeout:
                    self.on_timeout()
                break

            await asyncio.sleep(KEEPALIVE_INTERVAL)

    async def create_offer(self) -> dict:
        offer = await self.pc.createOffer()

        await self.pc.setLocalDescription(offer)

        return {
            "type": self.pc.localDescription.type,
            "sdp": self.pc.localDescription.sdp
        }

    async def set_answer(self, sdp: str, type: str = "answer"):
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp = sdp, type = type))

    async def create_answer(self, offer_sdp: str, offer_type: str = "offer") -> dict:
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp = offer_sdp, type = offer_type))
        
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)

        return {
            "type": self.pc.localDescription.type,
            "sdp": self.pc.localDescription.sdp
        }

    async def add_ice_candidate(self, candidate_dict: dict):
        raw: str | None = candidate_dict.get("candidate", "")

        if (not raw or raw == ""):
            return

        parts = raw.split()
        # candidate:foundation component protocol priority ip port typ type [raddr X rport Y]
        foundation = parts[0].replace("candidate:", "")
        component = int(parts[1])
        protocol = parts[2]
        priority = int(parts[3])
        ip = parts[4]
        port = int(parts[5])
        candidate_type = parts[7]

        related_address = None
        related_port = None

        for i, p in enumerate(parts):
            if (p == "raddr" and i + 1 < len(parts)):
                related_address = parts[i + 1]
            if (p == "rport" and i + 1 < len(parts)):
                related_port = int(parts[i + 1])

        candidate = RTCIceCandidate(
            component = component,
            foundation = foundation,
            ip = ip,
            port = port,
            priority = priority,
            protocol = protocol,
            type = candidate_type,
            relatedAddress = related_address,
            relatedPort = related_port,
            sdpMid = candidate_dict.get("sdpMid"),
            sdpMLineIndex = candidate_dict.get("sdpMLineIndex"),
        )

        await self.pc.addIceCandidate(candidate)

        logger.debug(f"[ICE]: Added remote candidate {ip}:{port} ({candidate_type})")

    async def close(self):
        await self.pc.close()
