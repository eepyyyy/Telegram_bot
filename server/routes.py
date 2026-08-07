import logging
from aiohttp import web
from sqlmodel import select
import crud
from database import async_session
from server import config
from server.stream import handle_telegram_stream

logger = logging.getLogger("server.routes")

routes = web.RouteTableDef()


@routes.get("/health")
async def health_check(request: web.Request):
    return web.json_response({"status": "ok", "service": "Telegram Cloud Streaming Server"})


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
