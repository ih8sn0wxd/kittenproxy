import aiohttp
from loguru import logger


async def exec_call(data: dict) -> tuple[int, dict]:
    async with aiohttp.ClientSession() as session:
        response: aiohttp.ClientResponse = await session.post(
            "https://calls.okcdn.ru/fb.do", data = data, ssl = False
        )

        logger.debug(f"[OkCDN]: Received {response.status} status code")

        return (response.status, await response.json())
