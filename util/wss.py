import json
import asyncio
import ssl
from websockets.asyncio.client import connect
from loguru import logger
from util.rtc_peer import RtcPeer
from util import protocol
from util.misc import encrypt, decrypt
from proxy import SocksProxy
from util.relay import Relay
import config

MEDIA_SETTINGS: dict = {
    "isAudioEnabled": True,
    "isVideoEnabled": False,
    "isScreenSharingEnabled": False,
    "isFastScreenSharingEnabled": False,
    "isAudioSharingEnabled": False,
    "isAnimojiEnabled": False,
}

class CallSession:
    def __init__(self, mode: str):
        self.mode = mode
        self.peer: RtcPeer | None = None
        self.participant_id: int | None = None
        self._sequence: int = 1
        self._connection = None
        self._proxy: SocksProxy | None = None
        self._relay: Relay | None = None
        self._disconnected: bool = False

    async def _send(self, data: dict) -> None:
        logger.info(f"[WebSocket]: Command = {data['command']}, Sequence = {self._sequence}")
        data["sequence"] = self._sequence
        await self._connection.send(json.dumps(data))
        self._sequence += 1

    async def connect(self, endpoint: str) -> None:
        logger.debug(f"[WebSocket]: Endpoint is {endpoint}")

        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        async with connect(endpoint, ssl = ssl_ctx) as connection:
            self._connection = connection

            while True:
                message: str = await connection.recv()

                if (not message.startswith("{")):
                    if message == "ping":
                        await connection.send("pong")

                    continue

                message: dict = json.loads(message)

                if (message.get("type") != "notification"):
                    continue

                notification = message["notification"]

                if (notification == "connection"):
                    await self._handle_connection(message)
                elif (notification == "settings-update"):
                    await self._handle_settings_update()
                elif (notification == "transmitted-data"):
                    await self._handle_transmitted_data(message)
                elif (notification == "accepted-call"):
                    logger.debug(f"[WebSocket]: Call accepted by {message.get('participantId')}")

    async def _handle_connection(self, message: dict) -> None:
        logger.success("[WebSocket]: Connection")

        conv_params = message["conversationParams"]
        self.peer = RtcPeer(stun = conv_params["stun"], turn = conv_params["turn"])

        self._setup_tunnel()

        target_state = "CALLED" if self.mode == "client" else "ACCEPTED"

        for p in message["conversation"]["participants"]:
            if (p.get("state") == target_state):
                self.participant_id = p["id"]
                break

        if (self.mode == "client"):
            self.peer.add_channel(config.TARGET_DATACHANNEL)

            await self._send({"command": "update-media-modifiers", "mediaModifiers": {"denoise": True, "denoiseAnn": True}})
            await self._send({"command": "change-options", "options": {"FEEDBACK": True}})

        elif (self.mode == "server"):
            await self._send({"command": "accept-call", "mediaSettings": MEDIA_SETTINGS})

    def _setup_tunnel(self):
        def send_frame(data: bytes):
            ch = self.peer.channels.get(config.TARGET_DATACHANNEL)

            if (ch and ch.readyState == "open"):
                ch.send(encrypt(data))

        if (self.mode == "client"):
            self._proxy = SocksProxy()
            self._proxy.bind(send_frame)

            def on_binary(msg: bytes):
                plaintext = decrypt(msg)
                frame_type, stream_id, payload = protocol.unpack(plaintext)
                self._proxy.on_frame(frame_type, stream_id, payload)

            def on_connected():
                asyncio.ensure_future(self._proxy.start())

        elif (self.mode == "server"):
            self._relay = Relay()
            self._relay.bind(send_frame)

            def on_binary(msg: bytes):
                plaintext = decrypt(msg)
                frame_type, stream_id, payload = protocol.unpack(plaintext)
                self._relay.on_frame(frame_type, stream_id, payload)

            def on_connected():
                logger.success("[Relay]: Ready to accept tunneled connections")

        def on_timeout():
            logger.warning("[Tunnel]: Peer timed out, closing session")
            asyncio.ensure_future(self._handle_disconnect())

        self.peer.on_binary = on_binary
        self.peer.on_connected = on_connected
        self.peer.on_timeout = on_timeout

    async def _handle_disconnect(self):
        logger.warning("[Session]: Disconnecting...")
        self._disconnected = True

        if (self._proxy):
            await self._proxy.stop()

        if (self._relay):
            await self._relay.stop()

        if (self.peer):
            await self.peer.close()

        if (self._connection):
            await self._connection.close()

    async def _handle_settings_update(self) -> None:
        logger.success("[WebSocket] [Notification]: Received settings-update")

        if (self.mode == "client"):
            sdp = await self.peer.create_offer()

            await self._send({
                "command": "transmit-data",
                "participantId": self.participant_id,
                "participantType": "USER",
                "data": {"animojiVersion": 2, "sdp": sdp},
            })

            await self._send({"command": "change-media-settings", "mediaSettings": MEDIA_SETTINGS})

        elif (self.mode == "server"):
            await self._send({"command": "change-media-settings", "mediaSettings": MEDIA_SETTINGS})
            await self._send({"command": "get-rooms", "withParticipants": False})
            await self._send({"command": "update-media-modifiers", "mediaModifiers": {"denoise": True, "denoiseAnn": True}})

        logger.info("[WebSocket]: Settings was sent successfully")

        if (self.mode == "client"):
            logger.info("[WebSocket]: Waiting for a call confirmation")

    async def _handle_transmitted_data(self, message: dict) -> None:
        data = message.get("data", {})

        if ("sdp" in data):
            sdp_type = data["sdp"]["type"]

            if (sdp_type == "offer"):
                logger.debug("[WebSocket]: Remote SDP offer")
                answer = await self.peer.create_answer(offer_sdp=data["sdp"]["sdp"], offer_type=sdp_type)

                await self._send({
                    "command": "transmit-data",
                    "participantId": self.participant_id,
                    "data": {"sdp": answer, "animojiVersion": 2},
                    "participantType": "USER",
                })

            elif (sdp_type == "answer"):
                if (self.peer.pc.signalingState == "stable"):
                    logger.debug("[WebSocket]: Ignoring SDP answer — already in stable state")
                else:
                    logger.debug("[WebSocket]: Remote SDP answer")
                    await self.peer.set_answer(sdp=data["sdp"]["sdp"], type=sdp_type)

        elif ("candidate" in data):
            candidate = data["candidate"]
            logger.debug(f"[WebSocket]: Remote ICE candidate: {candidate.get('candidate', '')[:60]}")

            await self.peer.add_ice_candidate(candidate)
