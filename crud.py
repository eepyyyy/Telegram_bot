import asyncio
from typing import List, Tuple, Any

from sqlmodel import select

import database
import gamdlUrl
import schema
from database import Tracks, AACTracks, AtmosTracks, MVTracks, User, async_session
from datetime import datetime, timezone


def get_track_model(format_type: str = "alac"):
    """
    Returns the appropriate SQLModel table class based on the format_type.
    """
    fmt = (format_type or "alac").lower()
    if fmt == "aac":
        return AACTracks
    elif fmt == "atmos":
        return AtmosTracks
    elif fmt in ("mv", "video"):
        return MVTracks
    return Tracks



async def save_albums(session: async_session, track_list: List[schema.TrackInputSchema]):
    """
    Saves albums to the database from a list of tracks.
    """
    for track_data in track_list:
        if track_data.album_id:
            album_obj = database.Albums(
                album_id=track_data.album_id,
                album=track_data.album,
                artist=track_data.artist,
                artwork=track_data.artwork,
            )
            await session.merge(album_obj)


async def save_tracks(session: async_session, track_list: List[schema.TrackInputSchema], format_type: str = "alac"):
    """
    Saves or updates tracks in the database.
    """
    model_cls = get_track_model(format_type)
    now_ts = datetime.now(timezone.utc)
    for track_data in track_list:
        track_obj = model_cls(
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
            updated_at=now_ts,
        )
        await session.merge(track_obj)


async def save_single_track(session: async_session, track_data: schema.TrackInputSchema, format_type: str = "alac"):
    """
    Saves or updates a single track in the database.
    Note: It does not call commit directly; it's expected to be managed by the session context.
    Args:
        session: The active database session.
        track_data: The track data schema to save.
        format_type: Quality format ('alac', 'aac', 'atmos', or 'mv').
    """
    if track_data.album_id:
        album_obj = database.Albums(
            album_id=track_data.album_id,
            album=track_data.album,
            artist=track_data.artist,
            artwork=track_data.artwork,
        )
        await session.merge(album_obj)
    
    model_cls = get_track_model(format_type)
    track_obj = model_cls(
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
        updated_at=datetime.now(timezone.utc),
    )
    await session.merge(track_obj)


async def check_db_for_urls(track_lists: List[schema.TrackInputSchema], format_type: str = "alac") -> Tuple[List[str], List[str]]:
    """
    Checks the database for existing tracks by ISRC or song_id to avoid re-downloading.
    Args:
        track_lists: List of tracks to check.
        format_type: Quality format ('alac', 'aac', 'atmos', or 'mv').
    Returns:
        A tuple containing:
            - List of file_ids for tracks already in the database.
            - List of URLs for tracks that need to be downloaded.
    """
    isrcs = [track.isrc for track in track_lists if track.isrc]
    song_ids = [track.song_id for track in track_lists if track.song_id]
    model_cls = get_track_model(format_type)

    async with async_session() as session:
        conds = []
        if isrcs:
            conds.append(model_cls.isrc.in_(isrcs))
        if song_ids:
            conds.append(model_cls.song_id.in_(song_ids))

        if not conds:
            return [], [str(track.url) for track in track_lists if track.url]

        from sqlmodel import or_
        statement = select(model_cls).where(or_(*conds))
        result = await session.exec(statement)
        db_tracks = result.all()

    cache_dict = {}
    for track in db_tracks:
        if track.file_id is not None:
            if track.isrc:
                cache_dict[track.isrc] = track.file_id
            if track.song_id:
                cache_dict[track.song_id] = track.file_id
    
    file_ids_to_send: List[str] = []
    urls_to_download: List[str] = []

    for track in track_lists:
        if track.isrc and track.isrc in cache_dict:
            file_ids_to_send.append(cache_dict[track.isrc])
        elif track.song_id and track.song_id in cache_dict:
            file_ids_to_send.append(cache_dict[track.song_id])
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