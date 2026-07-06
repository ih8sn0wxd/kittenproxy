import aiohttp
import asyncio
import json
import uuid
from loguru import logger

import config
from util import misc
from util.okcdn import exec_call
from util.wss import CallSession


async def init_call(mode: str, _endpoint: str | None = None) -> None:
    conversation_id: str = str(uuid.uuid4())

    logger.info("[Call]: Bootstrap")
    logger.debug(f"[Call]: Conversation ID = {conversation_id}")

    if (_endpoint is None):
        _, data = await exec_call(data = {
            "session_data": json.dumps({
                "version": 3,
                "device_id": str(uuid.uuid4()),
                "client_version": 1.1,
                "client_type": "SDK_JS",
                "auth_token": config.CLIENT_CALL_AUTH_TOKEN if mode == "client" else config.SERVER_CALL_AUTH_TOKEN,
            }),
            "method": "auth.anonymLogin",
            "format": "JSON",
            "application_key": "CGMMEJLGDIHBABABA",
        })

        session_key: str = data["session_key"]
        logger.success("[Call]: Received session key")

        await exec_call(data = {
            "method": "system.getInfo",
            "format": "JSON",
            "application_key": "CGMMEJLGDIHBABABA",
            "session_key": session_key,
        })

        _, data = await exec_call(data = {
            "conversationId": conversation_id,
            "isVideo": "false",
            "protocolVersion": 5,
            "payload": json.dumps({
                "is_video": False,
                "with_join_link": False,
                "join_by_link": False,
                "community_user_id": 0,
                "caller_app_id": 6287487,
            }),
            "onlyAdminCanShareMovie": "false",
            "externalIds": config.TARGET_BOT_USER_ID,
            "method": "vchat.startConversation",
            "format": "JSON",
            "application_key": "CGMMEJLGDIHBABABA",
            "session_key": session_key,
        })

        endpoint: str = data.get("endpoint") + "&platform=WEB&appVersion=1.1&version=5&device=browser&capabilities=2F7F&clientType=VK&tgt=retry"
    else:
        endpoint = _endpoint

    if (endpoint is None):
        logger.error("[Call] [FATAL]: Endpoint is None. Maybe rate limited?")
        return

    logger.success("[Call]: Establishing WebSocket connection")

    session = CallSession(mode = mode)

    try:
        await session.connect(endpoint)
    except Exception as e:
        logger.warning(f"[Call]: Session ended: {e}")


async def get_token() -> str | None:
    async with aiohttp.ClientSession() as session:
        response: aiohttp.ClientResponse = await session.post("https://login.vk.com/?act=web_token", data = {
            "version": 1,
            "app_id": "6287487",
        }, headers = {
            "Cookie": config.VK_COOKIES,
            "Origin": "https://vk.com",
        }, ssl = False)

        data: dict = await response.json()

        if (data["type"] == "okay"):
            logger.success(f"[Vk Auth]: Received new access token. Expires in: {data['data']['expires']}")

            return data["data"]["access_token"]

        return None


async def poll_call(mode: str) -> None:
    token: str = await get_token()

    if (token is None):
        logger.error("[Call Polling]: Auth token os None. Invalid cookies or fucked ip?")

        return

    async with aiohttp.ClientSession() as session:
        response: aiohttp.ClientResponse = await session.post("https://web.api.vk.com/method/messages.getDiff?v=5.282&client_id=6287487", data = {
            "group_id": 0,
            "from_version": 10041225,
            "conversations_limit": 10,
            "lp_version": 21,
            "extended_filters": "credentials,server_version,profiles,contacts,counters,groups,messages,folders,folders_with_peers",
            "nested_limit": 2,
            "counter_filters": "all",
            "supported_types": "business,channels,managed_groups,personal",
            "fields": "id,first_name,first_name_gen,first_name_acc,first_name_ins,first_name_dat,last_name,last_name_gen,last_name_acc,last_name_ins,sex,has_photo,photo_id,photo_50,photo_100,photo_200,contact_name,occupation,bdate,city,screen_name,online_info,verified,blacklisted,blacklisted_by_me,language,can_call,can_write_private_message,can_send_friend_request,can_invite_to_chats,friend_status,followers_count,profile_type,contacts,employee_mark,employee_working_state,is_service_account,image_status,photo_base,educational_profile,edu_roles,is_followers_mode_on,name,type,members_count,member_status,is_closed,can_message,deactivated,activity,ban_info,is_messages_blocked,can_send_notify,can_post_donut,site,reposts_disabled,description,action_button,menu,role,unread_count,wall,can_manage,disallow_manage_reason,age_limits,warning_notification",
            "access_token": token,
        }, headers = {
            "Cookie": config.VK_COOKIES,
        }, ssl = False)

        data: dict = await response.json()

        if ("response" not in data):
            return

        lp_key:    str = data["response"]["credentials"]["key"]
        lp_ts:     str = data["response"]["credentials"]["ts"]
        lp_server: str = data["response"]["credentials"]["server_lp"]

        logger.success("[Call Polling]: Polling credentials received")

        while True:
            response = await session.post(f"https://{lp_server}?mode=682&version=21", data = {
                "act": "a_check",
                "key": lp_key,
                "ts": lp_ts,
                "wait": 5,
            }, ssl = False)

            data = await response.json()

            if ("error" in data):
                logger.error(f"[Call Polling] [FATAL]: Vk said \"{data['error']}\" while polling incoming calls")

                return

            lp_ts = data["ts"]

            for update in data["updates"]:
                if (update[0] == 115): # call
                    call_id: str = update[1]["call_id"]
                    call_from: str = update[1]["caller_info"]["user_id"]

                    logger.success(f"[Call Polling]: Detected an new call from {call_from}. Call ID: {call_id}")

                    token: str = misc.extract_encrypted_call_data(update[1]["conversation_params"])["token"]

                    _, anon_data = await exec_call(data = {
                        "session_data": json.dumps({
                            "version": 3,
                            "device_id": str(uuid.uuid4()),
                            "client_version": 1.1,
                            "client_type": "SDK_JS",
                            "auth_token": config.SERVER_CALL_AUTH_TOKEN,
                        }),
                        "method": "auth.anonymLogin",
                        "format": "JSON",
                        "application_key": "CGMMEJLGDIHBABABA",
                    })

                    uid: str = anon_data["uid"]

                    logger.info(f"[Call Polling]: Call token from encrypted data: {token}, UID = {uid}")

                    endpoint: str = f"wss://videowebrtc.okcdn.ru/ws2?userId={uid}&entityType=USER&deviceIdx=0&conversationId={call_id}&token={token}&platform=WEB&appVersion=1.1&version=5&device=browser&capabilities=2F7F&clientType=vk&tgt=retry"

                    await init_call(mode = mode, _endpoint = endpoint)

                    logger.info("[Call Polling]: Session ended, resuming poll...")

            await asyncio.sleep(5)
