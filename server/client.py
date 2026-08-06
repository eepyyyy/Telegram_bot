import asyncio
import logging
import sys
from typing import Optional

# Python 3.12+ / 3.14 compatibility: Pyrogram sync wrapper requires an active event loop at import time
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from pyrogram import Client
from server import config


logger = logging.getLogger("server.client")

pyrogram_client: Optional[Client] = None

def get_pyrogram_client() -> Client:
    global pyrogram_client
    if pyrogram_client is not None:
        return pyrogram_client

    if not config.API_ID or not config.API_HASH:
        logger.warning(
            "API_ID or API_HASH is missing in .env! "
            "Direct Pyrogram cloud streaming will require API_ID and API_HASH from https://my.telegram.org"
        )
        # Initialize client with placeholder or raises when started
        api_id = int(config.API_ID) if config.API_ID and config.API_ID.isdigit() else 6
        api_hash = config.API_HASH or "eb06694183e94d25944848a21645f372"
    else:
        api_id = int(config.API_ID)
        api_hash = config.API_HASH

    pyrogram_client = Client(
        name="stream_bot_session",
        api_id=api_id,
        api_hash=api_hash,
        bot_token=config.TOKEN_API,
        in_memory=False,
        no_updates=True,
    )
    return pyrogram_client


async def start_client():
    client = get_pyrogram_client()
    logger.info("Starting Pyrogram MTProto Stream Client...")
    await client.start()
    me = await client.get_me()
    logger.info(f"Pyrogram Stream Client started as @{me.username} ({me.id})")
    
    # Pre-warm storage channel peer in Pyrogram session database
    if config.STORAGE_CHANNEL_ID:
        try:
            await client.get_chat(config.STORAGE_CHANNEL_ID)
            logger.info(f"Pre-warmed Pyrogram session for channel {config.STORAGE_CHANNEL_ID}")
        except Exception as e:
            logger.warning(f"Could not pre-warm channel {config.STORAGE_CHANNEL_ID}: {e}. Ensure bot is an Admin in the channel.")


async def stop_client():
    global pyrogram_client
    if pyrogram_client and pyrogram_client.is_connected:
        logger.info("Stopping Pyrogram MTProto Stream Client...")
        await pyrogram_client.stop()
