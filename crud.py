import asyncio
from typing import List, Tuple, Any

import database
import gamdlUrl
import schema
from database import Tracks, User, async_session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select


async def save_track_to_bot_db(track_lists: List[schema.TrackInputSchema]):
    """
    Takes a list of track schema objects and handles the async database save/merge operations.
    Args:
        track_lists: List of TrackInputSchema objects.
    """
    async with async_session() as session:
        async with session.begin():
            for track_data in track_lists:
                album_obj = database.Albums(
                    album_id=track_data.album_id,
                    album=track_data.album,
                    artist=track_data.artist,
                    artwork=track_data.artwork,
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
                    url=track_data.url,
                    isrc=track_data.isrc,
                    storefront=track_data.storefront,
                    artwork=track_data.artwork,
                )
                await session.merge(track_obj)
            # The context manager session.begin() will automatically commit at the end.


async def save_single_track(session: AsyncSession, track_data: schema.TrackInputSchema):
    """
    Saves or updates a single track in the database.
    Note: It does not call commit directly; it's expected to be managed by the session context.
    Args:
        session: The active database session.
        track_data: The track data schema to save.
    """
    album_obj = database.Albums(
        album_id=track_data.album_id,
        album=track_data.album,
        artist=track_data.artist,
        artwork=track_data.artwork,
    )
    await session.merge(album_obj)
    
    track_obj = database.Tracks(
        artist=track_data.artist,
        album=track_data.album,
        album_id=track_data.album_id,
        song_id=track_data.song_id,
        file_id=track_data.file_id,
        file_unique_id=track_data.file_unique_id,
        title=track_data.title,
        url=track_data.url,
        size=track_data.size,
        storefront=track_data.storefront,
        isrc=track_data.isrc,
        artwork=track_data.artwork,
        chat_id=track_data.chat_id,
        message_id=track_data.message_id,
    )
    await session.merge(track_obj)


async def check_db_for_urls(track_lists: List[schema.TrackInputSchema]) -> Tuple[List[str], List[str]]:
    """
    Checks the database for existing tracks by ISRC to avoid re-downloading.
    Args:
        track_lists: List of tracks to check.
    Returns:
        A tuple containing:
            - List of file_ids for tracks already in the database.
            - List of URLs for tracks that need to be downloaded.
    """
    isrcs = [track.isrc for track in track_lists if track.isrc]

    async with async_session() as session:
        if not isrcs:
            return [], [str(track.url) for track in track_lists if track.url]

        statement = select(Tracks).where(Tracks.isrc.in_(isrcs))
        result = await session.exec(statement)
        db_tracks = result.all()

    cache_dict = {
        track.isrc: track.file_id
        for track in db_tracks
        if track.file_id is not None
    }
    
    file_ids_to_send: List[str] = []
    urls_to_download: List[str] = []

    for track in track_lists:
        if track.isrc in cache_dict:
            file_ids_to_send.append(cache_dict[track.isrc])
        elif track.url:
            urls_to_download.append(str(track.url))
            
    return file_ids_to_send, urls_to_download


async def main():
    await database.init_db()
    test = await gamdlUrl.get_any_url("https://music.apple.com/in/playlist/%E5%A4%A2%E5%88%83/pl.u-38oWZ6esZbL0EGY")

    await check_db_for_urls(test)



if __name__ == "__main__":
    # This runs your async lifecycle natively in Python
    asyncio.run(main())