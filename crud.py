import aiogram
from database import get_session_maker
import database, sqlmodel, asyncio
import pydantic, Schema, gamdlUrl
from typing import List

async_session = get_session_maker()


async def save_track_to_bot_db(track_lists: List[Schema.TrackInputSchema]):
    async with async_session() as session:
        async with session.begin():

            for track_data in track_lists:
                album_obj = database.Albums(
                    album_id=track_data.album_id,
                    album=track_data.album,
                    artist=track_data.artist
                )
                await session.merge(album_obj)

                track_obj = database.Tracks(
                    artist=track_data.artist,
                    album=track_data.album,
                    album_id=track_data.album_id,
                    song_id=track_data.song_id,
                    file_id=None,
                    file_unique_id=None,
                    title=track_data.title,
                    url=track_data.url
                )
                await session.merge(track_obj)

async def main():
    await database.init_db()
    test = await gamdlUrl.get_any_url("https://music.apple.com/us/album/cigarettes-after-sex/1217977525")

    await save_track_to_bot_db(test)


if __name__ == "__main__":
    # This runs your async lifecycle natively in Python
    asyncio.run(main())