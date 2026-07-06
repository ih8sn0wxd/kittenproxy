import asyncio
from util import call
import sys
from loguru import logger

__VERSION__: str = "unstable_beta-0.1"

async def main() -> None:
    print(f"""
                                                                                                                                                    
                                                                                  
██ ▄█▀ ▄▄ ▄▄▄▄▄▄ ▄▄▄▄▄▄ ▄▄▄▄▄ ▄▄  ▄▄ █████▄ ▄▄▄▄   ▄▄▄  ▄▄ ▄▄ ▄▄ ▄▄   ▄▄▄▄  ▄▄ ▄▄ 
████   ██   ██     ██   ██▄▄  ███▄██ ██▄▄█▀ ██▄█▄ ██▀██ ▀█▄█▀ ▀███▀   ██▄█▀ ▀███▀  ({__VERSION__})
██ ▀█▄ ██   ██     ██   ██▄▄▄ ██ ▀██ ██     ██ ██ ▀███▀ ██ ██   █   ▄ ██      █   
                                                                                  \n\n""")
        
    if (not "--mode" in sys.argv):
        logger.error("[EntryPoint]: --mode variable is required (client/server)")
        exit()

    mode: str = sys.argv[sys.argv.index("--mode") + 1]

    logger.debug(f"[EntryPoint]: Launched with {mode} mode")

    if (mode == "server"):
        await call.poll_call(mode = mode)
    elif (mode == "client"):
        await call.init_call(mode = mode)
    else:
        logger.error(f"[EntryPoint]: Unknown mode {mode}")

asyncio.run(main())