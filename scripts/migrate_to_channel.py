import asyncio
import logging

# Python 3.12+ / 3.14 compatibility
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from sqlmodel import select
from pyrogram import Client
import database

from database import Tracks, AACTracks, AtmosTracks, async_session
from server import config
from server.client import get_pyrogram_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migrate_to_channel")


async def migrate_table(session, client: Client, model_cls, format_name: str):
    logger.info(f"Checking {format_name} tracks for migration...")
    statement = select(model_cls).where(model_cls.chat_id != config.STORAGE_CHANNEL_ID)
    result = await session.exec(statement)
    tracks = result.all()

    migrated_count = 0
    failed_count = 0

    for track in tracks:
        if not track.chat_id or not track.message_id:
            continue

        try:
            try:
                copied_msg = await client.copy_message(
                    chat_id=config.STORAGE_CHANNEL_ID,
                    from_chat_id=track.chat_id,
                    message_id=track.message_id
                )
            except Exception:
                # Try resolving source chat peer first
                await client.get_chat(track.chat_id)
                copied_msg = await client.copy_message(
                    chat_id=config.STORAGE_CHANNEL_ID,
                    from_chat_id=track.chat_id,
                    message_id=track.message_id
                )

            # Update DB with new channel chat_id and message_id
            track.chat_id = copied_msg.chat.id
            track.message_id = copied_msg.id
            session.add(track)
            await session.commit()
            migrated_count += 1
            logger.info(f"Successfully migrated track '{track.title}' ({track.song_id}) -> Channel Message ID {copied_msg.id}")
            await asyncio.sleep(1)  # Rate limit protection

        except Exception as e:
            failed_count += 1
            logger.warning(f"Could not migrate track '{track.title}' ({track.song_id}) from chat {track.chat_id}/msg {track.message_id}: {e}")


    logger.info(f"Completed {format_name} migration: {migrated_count} migrated, {failed_count} skipped/failed.")


async def main():
    await database.init_db()
    client = get_pyrogram_client()
    await client.start()

    logger.info(f"Resolving storage channel peer {config.STORAGE_CHANNEL_ID}...")
    try:
        storage_chat = await client.get_chat(config.STORAGE_CHANNEL_ID)
        logger.info(f"Successfully resolved storage channel: {storage_chat.title} ({storage_chat.id})")
    except Exception as e:
        logger.error(f"Could not resolve storage channel {config.STORAGE_CHANNEL_ID}: {e}. Ensure bot is an admin in the channel.")

    async with async_session() as session:
        await migrate_table(session, client, Tracks, "ALAC")
        await migrate_table(session, client, AACTracks, "AAC")
        await migrate_table(session, client, AtmosTracks, "Atmos")

    await client.stop()
    logger.info("Migration complete!")



if __name__ == "__main__":
    asyncio.run(main())
