from database import get_session_maker, Tracks
from sqlmodel import select, col
import database, sqlmodel, asyncio
from sqlalchemy.ext.asyncio import AsyncSession
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
                    url=track_data.title
                )
                await session.merge(track_obj)
                await session.commit()

async def save_single_track(session:AsyncSession, track_lists: Schema.TrackInputSchema):
    """
    Note: Doesn't call the Session
    Takes a track schema object and handles the async database save/merge operations.
    """
    album_obj = database.Albums(
        album_id=track_lists.album_id,
        album=track_lists.album,
        artist=track_lists.artist
    )
    await session.merge(album_obj)
    track_obj = database.Tracks(
        artist=track_lists.artist,
        album=track_lists.album,
        album_id=track_lists.album_id,
        song_id=track_lists.song_id,
        file_id=track_lists.file_id,
        file_unique_id=track_lists.file_unique_id,
        title=track_lists.title,
        url=track_lists.url
    )
    await session.merge(track_obj)
    await session.commit()


async def check_db_for_urls(track_lists: List[Schema.TrackInputSchema]):
    # get list of urls
    incoming = [track.song_id for track in track_lists]

    async with async_session() as session:
        print(incoming)

        statement = select(Tracks).where(col(Tracks.song_id).in_(incoming))
        result = await session.exec(statement)

        db_Tracks = result.all()
        print((db_Tracks))

    cache_dict = {
        track.song_id: track.file_id
        for track in db_Tracks
        if track.file_id is not None
        }
    file_ids_to_send = []
    urls_to_download = []

    for track in track_lists:
        if track.song_id in cache_dict:
            file_ids_to_send.append(cache_dict[track.song_id])
        else:
            urls_to_download.append(str(track.url))

    print(file_ids_to_send, urls_to_download)




async def main():
    await database.init_db()
    test = await gamdlUrl.get_any_url("https://music.apple.com/in/album/everything-i-know-about-love/1641539616")

    await save_track_to_bot_db(test)



if __name__ == "__main__":
    # This runs your async lifecycle natively in Python
    asyncio.run(main())