import logging
import os
import sys
from pathlib import Path
from aiohttp import web
from sqlmodel import select, or_, func, col, case
import crud
import gamdlHelpUrl
from database import Tracks, AACTracks, AtmosTracks, Albums, async_session
from server import config
from server.stream import handle_telegram_stream

# Ensure stdout/stderr handle UTF-8 symbols (e.g. copyright ℗) safely on Windows
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

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
    Uses multi-pattern ILIKE matching (including 'weeknd' / 'weekend' cross-matching)
    and ranks artist hits above title/album hits.
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

    # Build search patterns
    patterns = []
    if q:
        q_clean = q.lower()
        patterns.append(f"%{q_clean}%")
        
        # Handle 'weeknd' vs 'weekend' alternate spelling
        if "weeknd" in q_clean:
            patterns.append(f"%{q_clean.replace('weeknd', 'weekend')}%")
        elif "weekend" in q_clean:
            patterns.append(f"%{q_clean.replace('weekend', 'weeknd')}%")
            
        if "-" in q_clean:
            patterns.append(f"%{q_clean.replace('-', '')}%")

    async with async_session() as session:
        for model_cls, format_type in models_to_query:
            query = select(model_cls)

            conditions = []
            if available_only:
                conditions.append(model_cls.message_id.is_not(None))

            if patterns:
                or_conditions = []
                for p in patterns:
                    or_conditions.extend([
                        col(model_cls.title).ilike(p),
                        col(model_cls.artist).ilike(p),
                        col(model_cls.album).ilike(p),
                        col(model_cls.isrc).ilike(p),
                        col(model_cls.song_id).ilike(p),
                    ])
                conditions.append(or_(*or_conditions))

            if conditions:
                query = query.where(*conditions)

            result = await session.exec(query)
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

    # If searching, calculate relevance rank (Artist hits first, then Title hits, then Album hits)
    if q:
        q_clean = q.lower()
        search_terms = q_clean.split()
        
        def calculate_rank(track):
            artist = (track["artist"] or "").lower()
            title = (track["title"] or "").lower()
            
            # 1. Exact artist match (e.g. "the weeknd" == artist)
            if q_clean == artist:
                return (0, title)
            # 2. Artist contains full query or key alternate query
            if any(p.strip("%") in artist for p in patterns):
                return (1, title)
            # 3. Artist contains all search terms
            if all(term in artist for term in search_terms):
                return (2, title)
            # 4. Title match
            if any(p.strip("%") in title for p in patterns):
                return (3, title)
            # 5. Album / ISRC match
            return (4, title)

        items.sort(key=calculate_rank)
        total_count = len(items)
        items = items[offset : offset + limit]
    else:
        # Default sort by title
        items.sort(key=lambda x: (x["title"] or "").lower())
        total_count = len(items)
        items = items[offset : offset + limit]

    total_pages = (total_count + limit - 1) // limit if limit > 0 else 1

    return web.json_response({
        "items": items,
        "total": total_count,
        "page": page,
        "limit": limit,
        "pages": total_pages,
    })


@routes.get("/api/catalog/search")
async def search_apple_catalog(request: web.Request):
    """
    Searches Apple Music API catalog via gamdlHelpUrl for artists, albums, and tracks.
    Cross-checks songs with local DB to indicate download availability or Telegram Bot request.
    """
    q = request.query.get("q", "").strip()
    if not q:
        return web.json_response({"artists": [], "albums": [], "songs": []})

    try:
        api = await gamdlHelpUrl.get_api()
        
        # Check if input is direct Apple Music URL
        if q.startswith("http://") or q.startswith("https://"):
            meta = await gamdlHelpUrl.get_url_metadata(q)
            m_type = meta.get("type", "")
            if m_type == "artist":
                return web.json_response({
                    "artists": [{
                        "id": meta.get("artist_id"),
                        "name": meta.get("name"),
                        "url": meta.get("url"),
                        "artwork": meta.get("artwork")
                    }],
                    "albums": [],
                    "songs": []
                })
            elif m_type in ("album", "playlist"):
                songs_list = []
                for tr in meta.get("tracks", []):
                    songs_list.append({
                        "song_id": tr.get("song_id"),
                        "title": tr.get("title"),
                        "artist": tr.get("artist"),
                        "album": meta.get("title"),
                        "isrc": tr.get("isrc"),
                        "url": tr.get("url"),
                        "artwork": meta.get("artwork"),
                        "is_available": False,
                        "download_url": None,
                        "bot_request_cmd": f"/download {tr.get('url', '')}"
                    })
                return web.json_response({
                    "artists": [],
                    "albums": [{
                        "id": meta.get("album_id") or meta.get("playlist_id"),
                        "title": meta.get("title"),
                        "artist": meta.get("artist") or meta.get("curator"),
                        "url": meta.get("url"),
                        "artwork": meta.get("artwork")
                    }],
                    "songs": songs_list
                })

        # Standard term search via Apple Music API
        raw_res = await api.get_search_results(q, limit=10)
        results = raw_res.get("results", {}) if isinstance(raw_res, dict) else {}
        
        artists = []
        if "artists" in results:
            for item in results["artists"].get("data", []):
                attrs = item.get("attributes", {})
                artists.append({
                    "id": item.get("id"),
                    "name": attrs.get("name", "Unknown Artist"),
                    "url": attrs.get("url", ""),
                    "artwork": gamdlHelpUrl.get_artwork_url(attrs.get("artwork"), size=300),
                })
                
        albums = []
        if "albums" in results:
            for item in results["albums"].get("data", []):
                attrs = item.get("attributes", {})
                albums.append({
                    "id": item.get("id"),
                    "title": attrs.get("name", "Unknown Album"),
                    "artist": attrs.get("artistName", "Unknown Artist"),
                    "release_date": attrs.get("releaseDate", "N/A"),
                    "track_count": attrs.get("trackCount"),
                    "url": attrs.get("url", ""),
                    "artwork": gamdlHelpUrl.get_artwork_url(attrs.get("artwork"), size=300),
                })

        songs = []
        song_ids_to_check = []
        isrcs_to_check = []

        if "songs" in results:
            for item in results["songs"].get("data", []):
                attrs = item.get("attributes", {})
                sid = item.get("id")
                isrc = attrs.get("isrc")
                if sid:
                    song_ids_to_check.append(str(sid))
                if isrc:
                    isrcs_to_check.append(str(isrc))

                songs.append({
                    "song_id": sid,
                    "title": attrs.get("name", "Unknown Song"),
                    "artist": attrs.get("artistName", "Unknown Artist"),
                    "album": attrs.get("albumName", "Unknown Album"),
                    "isrc": isrc,
                    "url": attrs.get("url", ""),
                    "artwork": gamdlHelpUrl.get_artwork_url(attrs.get("artwork"), size=300),
                    "is_available": False,
                    "download_url": None,
                    "stream_url": None,
                    "bot_request_cmd": f"/download {attrs.get('url', '')}"
                })

        # Cross-reference database for download availability
        if song_ids_to_check or isrcs_to_check:
            db_map = {}
            async with async_session() as session:
                for model_cls, format_type in [(Tracks, "alac"), (AACTracks, "aac"), (AtmosTracks, "atmos")]:
                    stmt = select(model_cls).where(
                        or_(
                            col(model_cls.song_id).in_(song_ids_to_check),
                            col(model_cls.isrc).in_(isrcs_to_check)
                        )
                    )
                    res = await session.exec(stmt)
                    found_tracks = res.all()
                    for ft in found_tracks:
                        key = ft.song_id or ft.isrc
                        if key:
                            db_map[key] = {
                                "format": format_type,
                                "song_id": ft.song_id,
                                "message_id": ft.message_id,
                                "is_available": ft.message_id is not None
                            }

            for s in songs:
                key1 = str(s["song_id"])
                key2 = str(s["isrc"])
                if key1 in db_map:
                    s["is_available"] = db_map[key1]["is_available"]
                    fmt = db_map[key1]["format"]
                    sid = db_map[key1]["song_id"]
                    s["download_url"] = f"/download/{fmt}/{sid}"
                    s["stream_url"] = f"/stream/{fmt}/{sid}"
                elif key2 in db_map:
                    s["is_available"] = db_map[key2]["is_available"]
                    fmt = db_map[key2]["format"]
                    sid = db_map[key2]["song_id"]
                    s["download_url"] = f"/download/{fmt}/{sid}"
                    s["stream_url"] = f"/stream/{fmt}/{sid}"

        return web.json_response({
            "artists": artists,
            "albums": albums,
            "songs": songs,
            "bot_username": "applemusicdw_bot"
        })

    except Exception as e:
        logger.error(f"Catalog search error: {e}")
        return web.json_response({"artists": [], "albums": [], "songs": [], "error": str(e)})


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
