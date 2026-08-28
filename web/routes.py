import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional

from aiohttp import web
from sqlmodel import select, func, or_, col

import crud
import database
import gamdlHelpUrl
from database import Tracks, AACTracks, AtmosTracks, Albums, async_session
from web import config
from web.downloader import download_track_web

logger = logging.getLogger("web.routes")
routes = web.RouteTableDef()
STATIC_DIR = Path(__file__).resolve().parent / "static"


# 1. UI Routes
@routes.get("/")
@routes.get("/app")
@routes.get("/app/{tail:.*}")
async def serve_web_app(request: web.Request):
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise web.HTTPNotFound(text="index.html not found in web/static directory.")
    return web.FileResponse(index_file)


# 2. Health & Metrics
@routes.get("/health")
async def health_check(request: web.Request):
    return web.json_response({
        "status": "ok",
        "service": "Standalone Apple Music Web Downloader",
        "storage_dir": str(config.LOCAL_STORAGE_DIR)
    })


@routes.get("/api/stats")
async def get_stats(request: web.Request):
    async with async_session() as session:
        alac_cnt = int((await session.exec(select(func.count()).select_from(Tracks))).one() or 0)
        aac_cnt = int((await session.exec(select(func.count()).select_from(AACTracks))).one() or 0)
        atmos_cnt = int((await session.exec(select(func.count()).select_from(AtmosTracks))).one() or 0)
        albums_cnt = int((await session.exec(select(func.count()).select_from(Albums))).one() or 0)

        alac_sz = float((await session.exec(select(func.sum(Tracks.size)))).one() or 0.0)
        aac_sz = float((await session.exec(select(func.sum(AACTracks.size)))).one() or 0.0)
        atmos_sz = float((await session.exec(select(func.sum(AtmosTracks.size)))).one() or 0.0)

    total_tracks = alac_cnt + aac_cnt + atmos_cnt
    total_size_bytes = int(alac_sz + aac_sz + atmos_sz)

    return web.json_response({
        "total_tracks": total_tracks,
        "total_albums": albums_cnt,
        "total_size_bytes": total_size_bytes,
        "total_size_gb": round(total_size_bytes / (1024 ** 3), 2) if total_size_bytes else 0.0,
        "formats": {
            "alac": alac_cnt,
            "aac": aac_cnt,
            "atmos": atmos_cnt
        }
    })


# 3. Catalog API Proxies
@routes.get("/api/search")
async def proxy_search(request: web.Request):
    term = request.query.get("term", "").strip()
    country = request.query.get("country", "us").strip()
    entity = request.query.get("entity", "song").strip()
    limit = request.query.get("limit", "30").strip()

    if not term:
        return web.json_response({"results": []})

    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            url = f"https://itunes.apple.com/search?term={term}&country={country}&entity={entity}&limit={limit}"
            async with session.get(url) as resp:
                data = await resp.json(content_type=None)
                return web.json_response(data)
    except Exception as e:
        logger.error(f"Error in search proxy: {e}")
        return web.json_response({"results": [], "error": str(e)})


@routes.get("/api/lookup")
async def proxy_lookup(request: web.Request):
    item_id = request.query.get("id", "").strip()
    country = request.query.get("country", "us").strip()
    entity = request.query.get("entity", "").strip()
    limit = request.query.get("limit", "300").strip()

    if not item_id:
        return web.json_response({"results": []})

    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            url = f"https://itunes.apple.com/lookup?id={item_id}&country={country}"
            if entity:
                url += f"&entity={entity}"
            if limit:
                url += f"&limit={limit}"
            async with session.get(url) as resp:
                data = await resp.json(content_type=None)
                return web.json_response(data)
    except Exception as e:
        logger.error(f"Error in lookup proxy: {e}")
        return web.json_response({"results": [], "error": str(e)})


# 4. Direct Web Download Endpoint
@routes.post("/api/web/download")
async def web_download_request(request: web.Request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON payload"}, status=400)

    url = body.get("url", "").strip()
    format_type = body.get("format_type", "alac").strip().lower()
    resolution = body.get("resolution")
    codec = body.get("codec")

    if not url:
        return web.json_response({"error": "Apple Music URL is required"}, status=400)

    logger.info(f"[Web Request] Download requested for URL: {url} (Format: {format_type}, Res: {resolution}, Codec: {codec})")
    result = await download_track_web(url=url, format_type=format_type, resolution=resolution, codec=codec)


    if not result.get("success"):
        return web.json_response(result, status=500)

    return web.json_response(result)


# 5. File Download Endpoint
@routes.get("/download/{format_type}/{song_id}")
async def download_media_file(request: web.Request):
    format_type = request.match_info.get("format_type", "alac").lower()
    song_id = request.match_info.get("song_id")

    model_cls = crud.get_track_model(format_type)

    async with async_session() as session:
        statement = select(model_cls).where(model_cls.song_id == song_id)
        result = await session.exec(statement)
        track = result.first()

    target_dir = config.LOCAL_STORAGE_DIR / (format_type if format_type != "video" else "mv")
    local_file: Optional[Path] = None

    if target_dir.exists():
        for f in target_dir.glob("*"):
            if f.is_file() and not f.name.endswith(".tmp"):
                local_file = f
                break

    if local_file and local_file.exists():
        clean_name = f"{track.title if track else song_id}.{local_file.suffix.lstrip('.')}"
        return web.FileResponse(
            local_file,
            headers={
                "Content-Disposition": f'attachment; filename="{clean_name}"'
            }
        )

    if not track:
        raise web.HTTPNotFound(text=f"Track {song_id} ({format_type}) not found.")

    return web.json_response({
        "status": "pending",
        "message": f"Track {song_id} is registered in database. Initiate web download to generate file."
    })


# 6. Audio Streaming Endpoint (Range Header HTTP 206 Support)
@routes.get("/stream/{format_type}/{song_id}")
async def stream_media_file(request: web.Request):
    format_type = request.match_info.get("format_type", "alac").lower()
    song_id = request.match_info.get("song_id")

    target_dir = config.LOCAL_STORAGE_DIR / (format_type if format_type != "video" else "mv")
    local_file: Optional[Path] = None

    if target_dir.exists():
        for f in target_dir.glob("*"):
            if f.is_file() and not f.name.endswith(".tmp"):
                local_file = f
                break

    if local_file and local_file.exists():
        return web.FileResponse(local_file)

    raise web.HTTPNotFound(text=f"Stream target for song {song_id} ({format_type}) not found on local disk.")
