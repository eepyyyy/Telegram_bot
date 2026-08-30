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
    Saves albums to the database from a list of tracks without overwriting existing zip cache columns.
    """
    for track_data in track_list:
        if track_data.album_id:
            alb_id = str(track_data.album_id)
            stmt = select(database.Albums).where(database.Albums.album_id == alb_id)
            res = await session.exec(stmt)
            album_obj = res.first()
            if not album_obj:
                album_obj = database.Albums(
                    album_id=alb_id,
                    album=track_data.album,
                    artist=track_data.artist,
                    artwork=track_data.artwork,
                )
                session.add(album_obj)
            else:
                if track_data.album and not album_obj.album:
                    album_obj.album = track_data.album
                if track_data.artist and not album_obj.artist:
                    album_obj.artist = track_data.artist
                if track_data.artwork and not album_obj.artwork:
                    album_obj.artwork = track_data.artwork
                session.add(album_obj)


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
    Saves or updates a single track in the database without overwriting existing zip cache columns.
    """
    if track_data.album_id:
        alb_id = str(track_data.album_id)
        stmt = select(database.Albums).where(database.Albums.album_id == alb_id)
        res = await session.exec(stmt)
        album_obj = res.first()
        if not album_obj:
            album_obj = database.Albums(
                album_id=alb_id,
                album=track_data.album,
                artist=track_data.artist,
                artwork=track_data.artwork,
            )
            session.add(album_obj)
        else:
            if track_data.album and not album_obj.album:
                album_obj.album = track_data.album
            if track_data.artist and not album_obj.artist:
                album_obj.artist = track_data.artist
            if track_data.artwork and not album_obj.artwork:
                album_obj.artwork = track_data.artwork
            session.add(album_obj)
    
    model_cls = get_track_model(format_type)
    extra_kwargs = {}
    if issubclass(model_cls, MVTracks):
        if track_data.resolution:
            extra_kwargs["resolution"] = track_data.resolution
        if track_data.codec:
            extra_kwargs["codec"] = track_data.codec

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
        **extra_kwargs
    )
    await session.merge(track_obj)


async def get_mv_tracks_by_song_id(session: async_session, song_id: str) -> List[MVTracks]:
    """
    Returns all cached resolution entries for a Music Video song_id.
    """
    statement = select(MVTracks).where(MVTracks.song_id == song_id)
    result = await session.exec(statement)
    return result.all()



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
    urls = [str(track.url) for track in track_lists if track.url]
    model_cls = get_track_model(format_type)

    async with async_session() as session:
        conds = []
        if isrcs:
            conds.append(model_cls.isrc.in_(isrcs))
        if song_ids:
            conds.append(model_cls.song_id.in_(song_ids))
        if urls:
            conds.append(model_cls.url.in_(urls))

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
            if getattr(track, "url", None):
                cache_dict[str(track.url)] = track.file_id

    file_ids_to_send: List[str] = []
    urls_to_download: List[str] = []

    for track in track_lists:
        if track.isrc and track.isrc in cache_dict:
            file_ids_to_send.append(cache_dict[track.isrc])
        elif track.song_id and track.song_id in cache_dict:
            file_ids_to_send.append(cache_dict[track.song_id])
        elif track.url and str(track.url) in cache_dict:
            file_ids_to_send.append(cache_dict[str(track.url)])
        elif track.url:
            urls_to_download.append(str(track.url))

            
    return file_ids_to_send, urls_to_download


async def log_download(
    session: async_session,
    user_id: int,
    song_id: Optional[str],
    format_type: str,
    size: Optional[int],
    is_cached: bool
) -> None:
    """
    Logs a download transaction in download_history.
    """
    from database import DownloadHistory
    log_entry = DownloadHistory(
        user_id=user_id,
        song_id=song_id,
        format_type=format_type.lower(),
        is_cached=is_cached,
        size=size or 0,
        downloaded_at=datetime.now(timezone.utc)
    )
    session.add(log_entry)


async def get_alac_download_count_12h(session: async_session, user_id: int) -> int:
    """
    Counts non-cached ALAC downloads in the last 12 hours for the user.
    """
    from sqlmodel import func
    from database import DownloadHistory
    from datetime import timedelta
    
    cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
    statement = select(func.count()).select_from(DownloadHistory).where(
        DownloadHistory.user_id == user_id,
        DownloadHistory.format_type == "alac",
        DownloadHistory.is_cached == False,
        DownloadHistory.downloaded_at >= cutoff
    )
    result = await session.exec(statement)
    return result.one() or 0


async def get_user_download_stats(session: async_session, user_id: int) -> dict:
    """
    Retrieves aggregated download stats for a user.
    """
    from sqlmodel import func
    from database import DownloadHistory
    
    # 1. Total sizes
    stmt_size = select(func.sum(DownloadHistory.size)).where(
        DownloadHistory.user_id == user_id,
        DownloadHistory.is_cached == False
    )
    res_size = await session.exec(stmt_size)
    total_size = res_size.one() or 0
    
    stmt_del_size = select(func.sum(DownloadHistory.size)).where(
        DownloadHistory.user_id == user_id
    )
    res_del_size = await session.exec(stmt_del_size)
    total_delivered_size = res_del_size.one() or 0
    
    # 2. Counts by format_type
    stmt_formats = select(DownloadHistory.format_type, func.count(DownloadHistory.id)).where(
        DownloadHistory.user_id == user_id
    ).group_by(DownloadHistory.format_type)
    res_formats = await session.exec(stmt_formats)
    formats_counts = {fmt: cnt for fmt, cnt in res_formats.all()}
    
    # 3. Cached vs Non-cached counts
    stmt_cache = select(DownloadHistory.is_cached, func.count(DownloadHistory.id)).where(
        DownloadHistory.user_id == user_id
    ).group_by(DownloadHistory.is_cached)
    res_cache = await session.exec(stmt_cache)
    cache_counts = {is_cached: cnt for is_cached, cnt in res_cache.all()}
    
    return {
        "total_size": total_size,
        "total_delivered_size": total_delivered_size,
        "alac_count": formats_counts.get("alac", 0),
        "aac_count": formats_counts.get("aac", 0),
        "atmos_count": formats_counts.get("atmos", 0),
        "mv_count": formats_counts.get("mv", 0),
        "cached_count": cache_counts.get(True, 0),
        "uncached_count": cache_counts.get(False, 0)
    }


async def auto_fix_album_zip_columns():
    """
    Dynamically applies missing album ZIP columns if not present in the database.
    """
    from sqlalchemy import text
    stmts = [
        "ALTER TABLE albums ADD COLUMN IF NOT EXISTS alac_zip_file_id VARCHAR;",
        "ALTER TABLE albums ADD COLUMN IF NOT EXISTS aac_zip_file_id VARCHAR;",
        "ALTER TABLE albums ADD COLUMN IF NOT EXISTS atmos_zip_file_id VARCHAR;",
        "ALTER TABLE albums ADD COLUMN IF NOT EXISTS alac_gofile_url VARCHAR;",
        "ALTER TABLE albums ADD COLUMN IF NOT EXISTS aac_gofile_url VARCHAR;",
        "ALTER TABLE albums ADD COLUMN IF NOT EXISTS atmos_gofile_url VARCHAR;",
    ]
    for s in stmts:
        try:
            async with database.engine.begin() as conn:
                await conn.execute(text(s))
        except Exception:
            pass


async def get_cached_album_zip(session: async_session, album_id: Any, format_type: str = "alac") -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (zip_file_id, gofile_url) for a cached album ZIP archive.
    """
    if not album_id:
        return None, None

    fmt = (format_type or "alac").lower()
    alb_id_str = str(album_id)

    for attempt in range(2):
        try:
            stmt = select(database.Albums).where(database.Albums.album_id == alb_id_str)
            result = await session.exec(stmt)
            album = result.first()
            if not album:
                return None, None

            if fmt == "aac":
                return getattr(album, "aac_zip_file_id", None), getattr(album, "aac_gofile_url", None)
            elif fmt == "atmos":
                return getattr(album, "atmos_zip_file_id", None), getattr(album, "atmos_gofile_url", None)
            else:
                return getattr(album, "alac_zip_file_id", None), getattr(album, "alac_gofile_url", None)
        except Exception as e:
            if attempt == 0 and "does not exist" in str(e).lower():
                print("Missing album columns detected. Auto-applying migration...")
                await auto_fix_album_zip_columns()
                continue
            print(f"Error fetching cached album zip for {album_id}: {e}")
            return None, None

    return None, None


async def save_cached_album_zip(
    session: async_session,
    album_id: Any,
    album_name: Optional[str] = None,
    artist: Optional[str] = None,
    artwork: Optional[str] = None,
    format_type: str = "alac",
    zip_file_id: Optional[str] = None,
    gofile_url: Optional[str] = None
) -> None:
    """
    Saves or updates cached album ZIP file_id and/or Gofile URL in the database.
    """
    if not album_id:
        return

    fmt = (format_type or "alac").lower()
    alb_id_str = str(album_id)

    for attempt in range(2):
        try:
            stmt = select(database.Albums).where(database.Albums.album_id == alb_id_str)
            result = await session.exec(stmt)
            album = result.first()

            if not album:
                album = database.Albums(
                    album_id=alb_id_str,
                    album=album_name,
                    artist=artist,
                    artwork=artwork
                )

            if album_name and not album.album:
                album.album = album_name
            if artist and not album.artist:
                album.artist = artist
            if artwork and not album.artwork:
                album.artwork = artwork

            if fmt == "aac":
                if zip_file_id:
                    album.aac_zip_file_id = zip_file_id
                if gofile_url:
                    album.aac_gofile_url = gofile_url
            elif fmt == "atmos":
                if zip_file_id:
                    album.atmos_zip_file_id = zip_file_id
                if gofile_url:
                    album.atmos_gofile_url = gofile_url
            else:
                if zip_file_id:
                    album.alac_zip_file_id = zip_file_id
                if gofile_url:
                    album.alac_gofile_url = gofile_url

            session.add(album)
            await session.commit()
            print(f"💾 Successfully saved cached {fmt.upper()} ZIP for album {alb_id_str} (zip_fid={zip_file_id})")
            return
        except Exception as e:
            if attempt == 0 and "does not exist" in str(e).lower():
                print("Missing album columns detected on save. Auto-applying migration...")
                await auto_fix_album_zip_columns()
                continue
            print(f"Error saving cached album zip for {album_id}: {e}")



async def main():
    await database.init_db()
    test = await gamdlUrl.get_any_url("https://music.apple.com/in/playlist/%E5%A4%A2%E5%88%83/pl.u-38oWZ6esZbL0EGY")

    await check_db_for_urls(test)



if __name__ == "__main__":
    # This runs your async lifecycle natively in Python
    asyncio.run(main())