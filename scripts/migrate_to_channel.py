import asyncio
import logging
from sqlmodel import select
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramBadRequest

import database
from database import Tracks, AACTracks, AtmosTracks, async_session
from server import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("migrate_to_channel")


async def migrate_tracks_by_file_id(bot: Bot, session, model_cls, format_name: str):
    logger.info(f"Scanning {format_name} tracks for channel migration...")
    
    # Query tracks where chat_id is not already the target channel or message_id is NULL
    statement = select(model_cls).where(
        (model_cls.chat_id != config.STORAGE_CHANNEL_ID) | (model_cls.message_id == None)
    )
    result = await session.exec(statement)
    tracks = result.all()

    total_to_migrate = len(tracks)
    logger.info(f"Found {total_to_migrate} {format_name} tracks to upload/migrate to Backup Channel {config.STORAGE_CHANNEL_ID}.")

    migrated_count = 0
    failed_count = 0

    for idx, track in enumerate(tracks, 1):
        if not track.file_id:
            logger.warning(f"[{idx}/{total_to_migrate}] Track '{track.title}' ({track.song_id}) has no file_id in DB, skipping.")
            failed_count += 1
            continue

        success = False
        while not success:
            try:
                caption_text = f"🎵 <b>{track.title or 'Unknown'}</b> - {track.artist or 'Unknown'}\n💿 {track.album or ''}\n🆔 <code>{track.song_id}</code>"
                
                sent_msg = await bot.send_audio(
                    chat_id=config.STORAGE_CHANNEL_ID,
                    audio=track.file_id,
                    caption=caption_text,
                    parse_mode="HTML"
                )

                # Save new backup channel chat_id and message_id to database
                track.chat_id = sent_msg.chat.id
                track.message_id = sent_msg.message_id
                session.add(track)
                await session.commit()

                migrated_count += 1
                success = True
                logger.info(f"[{idx}/{total_to_migrate}] Migrated '{track.title}' -> Channel Message ID {sent_msg.message_id}")
                
                # Small delay to respect Telegram Channel posting limits
                await asyncio.sleep(1.2)

            except TelegramRetryAfter as e:
                logger.warning(f"Telegram FloodWait hit. Sleeping for {e.retry_after} seconds...")
                await asyncio.sleep(e.retry_after + 1)
            except TelegramBadRequest as e:
                failed_count += 1
                logger.error(f"[{idx}/{total_to_migrate}] Failed to send audio for '{track.title}' ({track.song_id}): {e}")
                success = True  # Move to next track
            except Exception as e:
                failed_count += 1
                logger.error(f"[{idx}/{total_to_migrate}] Unexpected error for track '{track.title}' ({track.song_id}): {e}")
                success = True  # Move to next track

    logger.info(f"Finished {format_name} migration: {migrated_count} succeeded, {failed_count} failed out of {total_to_migrate}.")


async def main():
    await database.init_db()
    
    if not config.TOKEN_API:
        logger.error("TOKEN_API is missing in .env!")
        return

    logger.info(f"Initializing Bot API client for channel migration...")
    bot = Bot(token=config.TOKEN_API)

    # Test channel accessibility via Bot API
    try:
        ping_msg = await bot.send_message(
            chat_id=config.STORAGE_CHANNEL_ID,
            text="🚀 <b>Storage Vault Migration Initialized</b>",
            parse_mode="HTML"
        )
        logger.info(f"Successfully verified Channel {config.STORAGE_CHANNEL_ID} access! Test Message ID: {ping_msg.message_id}")
    except Exception as e:
        logger.error(
            f"CRITICAL: Bot cannot send messages to channel {config.STORAGE_CHANNEL_ID}: {e}\n"
            f"Please ensure @applemusicdw_bot is an Administrator in channel {config.STORAGE_CHANNEL_ID} with Post Messages permission."
        )
        await bot.session.close()
        return

    async with async_session() as session:
        await migrate_tracks_by_file_id(bot, session, Tracks, "ALAC")

    await bot.session.close()
    logger.info("🎉 All ALAC tracks successfully migrated to Backup Channel storage!")



if __name__ == "__main__":
    asyncio.run(main())
