import logging
import os
from pathlib import Path
from aiohttp import web
from sqlmodel import select, or_, func, col
import crud
from database import Tracks, AACTracks, AtmosTracks, Albums, async_session
from server import config
from server.stream import handle_telegram_stream

logger = logging.getLogger("server.routes")

routes = web.RouteTableDef()
APP_DIR = Path(__file__).resolve().parent.parent / "app"


@routes.get("/health")
async def health_check(request: web.Request):
    return web.json_response({"status": "ok", "service": "Telegram Cloud Streaming Server"})


@routes.get("/api/stats")
async def get_stats(request: web.Request):
    """
    Returns database summary metrics for tracks and albums.
    """
    async with async_session() as session:
        alac_res = await session.exec(select(func.count()).select_from(Tracks))
        alac_cnt = alac_res.one() or 0

        aac_res = await session.exec(select(func.count()).select_from(AACTracks))
        aac_cnt = aac_res.one() or 0

        atmos_res = await session.exec(select(func.count()).select_from(AtmosTracks))
        atmos_cnt = atmos_res.one() or 0

        albums_res = await session.exec(select(func.count()).select_from(Albums))
        albums_cnt = albums_res.one() or 0

        # Available counts (where message_id is not null)
        alac_avail_res = await session.exec(select(func.count()).select_from(Tracks).where(Tracks.message_id.is_not(None)))
        alac_avail = alac_avail_res.one() or 0

        aac_avail_res = await session.exec(select(func.count()).select_from(AACTracks).where(AACTracks.message_id.is_not(None)))
        aac_avail = aac_avail_res.one() or 0

        atmos_avail_res = await session.exec(select(func.count()).select_from(AtmosTracks).where(AtmosTracks.message_id.is_not(None)))
        atmos_avail = atmos_avail_res.one() or 0

    total_tracks = alac_cnt + aac_cnt + atmos_cnt
    total_available = alac_avail + aac_avail + atmos_avail

    return web.json_response({
        "total_tracks": total_tracks,
        "available_tracks": total_available,
        "total_albums": albums_cnt,
        "formats": {
            "alac": {"total": alac_cnt, "available": alac_avail},
            "aac": {"total": aac_cnt, "available": aac_avail},
            "atmos": {"total": atmos_cnt, "available": atmos_avail},
        }
    })


@routes.get("/api/tracks")
async def list_tracks(request: web.Request):
    """
    List tracks with search, format filtering, availability filter, and pagination.
    """
    params = request.query
    fmt = params.get("format", "all").lower()
    q = params.get("q", "").strip()
    available_only = params.get("available_only", "false").lower() == "true"
    
    try:
        page = max(1, int(params.get("page", 1)))
    except ValueError:
        page = 1

    try:
        limit = min(100, max(1, int(params.get("limit", 20))))
    except ValueError:
        limit = 20

    offset = (page - 1) * limit

    # Determine which models to query
    models_to_query = []
    if fmt == "alac":
        models_to_query = [(Tracks, "alac")]
    elif fmt == "aac":
        models_to_query = [(AACTracks, "aac")]
    elif fmt == "atmos":
        models_to_query = [(AtmosTracks, "atmos")]
    else:
        models_to_query = [(Tracks, "alac"), (AACTracks, "aac"), (AtmosTracks, "atmos")]

    items = []
    total_count = 0

    async with async_session() as session:
        for model_cls, format_type in models_to_query:
            query = select(model_cls)

            conditions = []
            if available_only:
                conditions.append(model_cls.message_id.is_not(None))

            if q:
                search_pattern = f"%{q}%"
                conditions.append(
                    or_(
                        col(model_cls.title).ilike(search_pattern),
                        col(model_cls.artist).ilike(search_pattern),
                        col(model_cls.album).ilike(search_pattern),
                        col(model_cls.isrc).ilike(search_pattern),
                        col(model_cls.song_id).ilike(search_pattern),
                    )
                )

            if conditions:
                query = query.where(*conditions)

            # Count total for this model
            count_stmt = select(func.count()).select_from(query.subquery())
            count_res = await session.exec(count_stmt)
            total_count += count_res.one() or 0

            # Execute pagination query
            paged_query = query.order_by(model_cls.title, model_cls.song_id).offset(offset).limit(limit)
            result = await session.exec(paged_query)
            tracks_list = result.all()

            for t in tracks_list:
                is_avail = t.message_id is not None
                items.append({
                    "song_id": t.song_id,
                    "title": t.title or "Unknown Track",
                    "artist": t.artist or "Unknown Artist",
                    "album": t.album or "Unknown Album",
                    "album_id": t.album_id,
                    "format": format_type,
                    "size": t.size,
                    "isrc": t.isrc,
                    "artwork": t.artwork,
                    "chat_id": t.chat_id,
                    "message_id": t.message_id,
                    "is_available": is_avail,
                    "stream_url": f"/stream/{format_type}/{t.song_id}",
                    "download_url": f"/download/{format_type}/{t.song_id}",
                    "info_url": f"/info/{format_type}/{t.song_id}",
                })

    # Sort combined items if format is 'all'
    if fmt == "all":
        items.sort(key=lambda x: (x["title"] or "").lower())
        items = items[:limit]

    total_pages = (total_count + limit - 1) // limit if limit > 0 else 1

    return web.json_response({
        "items": items,
        "total": total_count,
        "page": page,
        "limit": limit,
        "pages": total_pages,
    })


@routes.get("/info/{format_type}/{song_id}")
async def get_track_info(request: web.Request):
    format_type = request.match_info.get("format_type", "alac")
    song_id = request.match_info.get("song_id")

    model_cls = crud.get_track_model(format_type)

    async with async_session() as session:
        statement = select(model_cls).where(model_cls.song_id == song_id)
        result = await session.exec(statement)
        track = result.first()

    if not track:
        raise web.HTTPNotFound(text=f"Track {song_id} ({format_type}) not found in database.")

    base_url = config.STREAM_SERVER_URL.rstrip("/")
    stream_url = f"{base_url}/stream/{format_type}/{song_id}"
    download_url = f"{base_url}/download/{format_type}/{song_id}"

    return web.json_response({
        "song_id": track.song_id,
        "title": track.title,
        "artist": track.artist,
        "album": track.album,
        "format": format_type,
        "size": track.size,
        "isrc": track.isrc,
        "artwork": track.artwork,
        "chat_id": track.chat_id,
        "message_id": track.message_id,
        "is_available": track.message_id is not None,
        "stream_url": stream_url,
        "download_url": download_url,
    })


@routes.get("/stream/{format_type}/{song_id}")
async def stream_track(request: web.Request):
    format_type = request.match_info.get("format_type", "alac")
    song_id = request.match_info.get("song_id")

    model_cls = crud.get_track_model(format_type)

    async with async_session() as session:
        statement = select(model_cls).where(model_cls.song_id == song_id)
        result = await session.exec(statement)
        track = result.first()

    if not track:
        raise web.HTTPNotFound(text=f"Track {song_id} ({format_type}) not found in database.")

    chat_id = track.chat_id or config.STORAGE_CHANNEL_ID
    message_id = track.message_id

    if not message_id:
        raise web.HTTPBadRequest(text=f"Track {song_id} does not have a cached Telegram message_id.")

    # Redirect to TG-FileStreamBot if enabled
    if config.USE_FILESTREAMBOT_REDIRECT:
        fsb_url = f"{config.FILESTREAMBOT_BASE_URL}/watch/{message_id}"
        logger.info(f"Redirecting stream request for track {song_id} to TG-FileStreamBot: {fsb_url}")
        raise web.HTTPFound(location=fsb_url)

    ext = "caf" if format_type == "atmos" else "m4a"
    clean_title = "".join(c for c in (track.title or "track") if c.isalnum() or c in (" ", "_", "-")).strip()
    filename = f"{clean_title}.{ext}"

    return await handle_telegram_stream(
        request=request,
        chat_id=chat_id,
        message_id=message_id,
        as_attachment=False,
        override_filename=filename
    )


@routes.get("/download/{format_type}/{song_id}")
async def download_track(request: web.Request):
    format_type = request.match_info.get("format_type", "alac")
    song_id = request.match_info.get("song_id")

    model_cls = crud.get_track_model(format_type)

    async with async_session() as session:
        statement = select(model_cls).where(model_cls.song_id == song_id)
        result = await session.exec(statement)
        track = result.first()

    if not track:
        raise web.HTTPNotFound(text=f"Track {song_id} ({format_type}) not found in database.")

    chat_id = track.chat_id or config.STORAGE_CHANNEL_ID
    message_id = track.message_id

    if not message_id:
        raise web.HTTPBadRequest(text=f"Track {song_id} does not have a cached Telegram message_id.")

    # Redirect to TG-FileStreamBot if enabled
    if config.USE_FILESTREAMBOT_REDIRECT:
        fsb_url = f"{config.FILESTREAMBOT_BASE_URL}/{message_id}?download=true"
        logger.info(f"Redirecting download request for track {song_id} to TG-FileStreamBot: {fsb_url}")
        raise web.HTTPFound(location=fsb_url)

    ext = "caf" if format_type == "atmos" else "m4a"
    clean_title = "".join(c for c in (track.title or "track") if c.isalnum() or c in (" ", "_", "-")).strip()
    filename = f"{clean_title}.{ext}"

    return await handle_telegram_stream(
        request=request,
        chat_id=chat_id,
        message_id=message_id,
        as_attachment=True,
        override_filename=filename
    )


# Static File & UI Routes
@routes.get("/")
async def root_redirect(request: web.Request):
    raise web.HTTPFound(location="/app")


@routes.get("/app")
@routes.get("/app/{tail:.*}")
async def serve_app(request: web.Request):
    tail = request.match_info.get("tail", "")
    file_path = APP_DIR / tail if tail else APP_DIR / "index.html"
    if file_path.is_dir() or not file_path.exists():
        file_path = APP_DIR / "index.html"
    if not file_path.exists():
        raise web.HTTPNotFound(text="UI build not found in /app directory.")
    return web.FileResponse(file_path)
