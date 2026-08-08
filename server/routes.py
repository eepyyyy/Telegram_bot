import logging
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from aiohttp import web
from sqlmodel import select, or_, func, col, case
import crud
import gamdlHelpUrl
from database import Tracks, AACTracks, AtmosTracks, Albums, async_session
from server import config
from server.stream import handle_telegram_stream

# Ensure stdout/stderr handle UTF-8 symbols safely on Windows
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


# Helper functions for Lyrics Parser Ecosystem
def parse_time(time_str: str) -> float:
    """Converts TTML time string (e.g. '27.395', '1:00.964', '01:23.456') to seconds float."""
    if not time_str:
        return 0.0
    time_str = time_str.rstrip('s')
    parts = time_str.split(':')
    try:
        if len(parts) == 1:
            return float(parts[0])
        elif len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    except ValueError:
        pass
    return 0.0


def format_lrc_timestamp(seconds: float) -> str:
    """Formats seconds into [mm:ss.xx] LRC format."""
    mins = int(seconds // 60)
    secs = seconds % 60
    return f"[{mins:02d}:{secs:05.2f}]"


def parse_ttml_lyrics(ttml_xml: str):
    """
    Parses Apple Music TTML XML string into 4 ecosystem formats:
    - lrc: Synced LRC file format string
    - plain: Plain text lyrics string
    - ttml: Raw TTML XML
    - synced: Array of dicts with start, end, text, part
    """
    synced_lines = []
    plain_lines = []
    lrc_lines = []

    if not ttml_xml:
        return {"lrc": "", "plain": "", "ttml": "", "synced": []}

    try:
        root = ET.fromstring(ttml_xml)
        for body in root.findall("{http://www.w3.org/ns/ttml}body"):
            for div in body.findall("{http://www.w3.org/ns/ttml}div"):
                part_name = div.attrib.get("{http://music.apple.com/lyric-ttml-internal}songPart", "")
                for p in div.findall("{http://www.w3.org/ns/ttml}p"):
                    text = "".join(p.itertext()).strip()
                    begin_attr = p.attrib.get("begin", "0")
                    end_attr = p.attrib.get("end", "0")

                    if not text:
                        continue

                    start_sec = parse_time(begin_attr)
                    end_sec = parse_time(end_attr)

                    synced_lines.append({
                        "start": start_sec,
                        "end": end_sec,
                        "text": text,
                        "part": part_name
                    })
                    plain_lines.append(text)
                    lrc_lines.append(f"{format_lrc_timestamp(start_sec)} {text}")

    except Exception as e:
        logger.error(f"Error parsing TTML lyrics: {e}")

    return {
        "lrc": "\n".join(lrc_lines),
        "plain": "\n".join(plain_lines),
        "ttml": ttml_xml,
        "synced": synced_lines
    }


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

        # Sum total file sizes across tables
        alac_sz_res = await session.exec(select(func.sum(Tracks.size)))
        alac_sz = alac_sz_res.one() or 0

        aac_sz_res = await session.exec(select(func.sum(AACTracks.size)))
        aac_sz = aac_sz_res.one() or 0

        atmos_sz_res = await session.exec(select(func.sum(AtmosTracks.size)))
        atmos_sz = atmos_sz_res.one() or 0

    total_tracks = alac_cnt + aac_cnt + atmos_cnt
    total_available = alac_avail + aac_avail + atmos_avail
    total_size_bytes = int((alac_sz or 0) + (aac_sz or 0) + (atmos_sz or 0))
    total_size_gb = round(total_size_bytes / (1024 ** 3), 2) if total_size_bytes else 0.0

    return web.json_response({
        "total_tracks": total_tracks,
        "available_tracks": total_available,
        "total_albums": albums_cnt,
        "total_size_bytes": total_size_bytes,
        "total_size_gb": total_size_gb,
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
        # Default sort: Show latest available/downloadable tracks first, ordered by newest ID
        def get_latest_key(x):
            avail_score = 0 if x.get("is_available") else 1
            msg_id = x.get("message_id") or 0
            song_id_num = 0
            sid = str(x.get("song_id") or "")
            if sid.isdigit():
                song_id_num = int(sid)
            return (avail_score, -msg_id, -song_id_num)

        items.sort(key=get_latest_key)
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


import base64
import hmac
import hashlib
import json
from urllib.parse import parse_qsl
from aiogram import Bot
from queues import download_queue, user_in_queue, user_pending_jobs, is_user_busy

def validate_telegram_init_data(init_data: str, bot_token: str) -> dict:
    """Validates Telegram WebApp initData HMAC signature."""
    if not init_data or not bot_token:
        return None
    try:
        parsed_data = dict(parse_qsl(init_data, keep_blank_values=True))
        hash_val = parsed_data.pop("hash", None)
        if not hash_val:
            return None
        
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed_data.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        
        if calculated_hash == hash_val:
            return json.loads(parsed_data.get("user", "{}"))
    except Exception as e:
        logger.error(f"Telegram initData validation error: {e}")
    return None


@routes.get("/api/telegram/encode-url")
async def encode_telegram_deeplink(request: web.Request):
    """
    Encodes Apple Music URL into Telegram deep-link parameter (dl_base64).
    """
    url = request.query.get("url", "").strip()
    if not url:
        return web.json_response({"error": "URL parameter required"}, status=400)

    b64 = base64.urlsafe_b64encode(url.encode('utf-8')).decode('utf-8').rstrip('=')
    param = f"dl_{b64}"
    bot_username = "applemusicdw_bot"
    deeplink = f"https://t.me/{bot_username}?start={param}"

    return web.json_response({
        "url": url,
        "encoded_param": param,
        "bot_username": bot_username,
        "deeplink": deeplink
    })


@routes.post("/api/telegram/request-download")
async def request_telegram_download(request: web.Request):
    """
    Directly enqueues a download request to the user's Telegram chat from the Web App.
    Validates Telegram initData HMAC or authenticated user context.
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    init_data = body.get("init_data", "").strip()
    target_url = body.get("url", "").strip()
    chat_id_override = body.get("chat_id")

    if not target_url:
        return web.json_response({"error": "Target track URL is required"}, status=400)

    user_id = None
    user_data = None

    if init_data:
        bot_token = os.getenv("TOKEN_API", "").strip()
        user_data = validate_telegram_init_data(init_data, bot_token)
        if user_data:
            user_id = user_data.get("id")

    if not user_id and chat_id_override:
        try:
            user_id = int(chat_id_override)
        except (ValueError, TypeError):
            pass

    if not user_id:
        return web.json_response({
            "error": "Telegram authorization required.",
            "message": "Please launch via Telegram Mini App or connect your Telegram account."
        }, status=401)

    if is_user_busy(user_id):
        return web.json_response({
            "error": "User Busy",
            "message": "You already have an active download in progress in Telegram. Please wait until it completes."
        }, status=429)

    try:
        bot_token = os.getenv("TOKEN_API", "").strip()
        bot = Bot(token=bot_token)
        
        msg = await bot.send_message(
            chat_id=user_id,
            text=target_url
        )
        await bot.session.close()

        user_in_queue.add(user_id)
        user_pending_jobs[user_id] = 1
        position = download_queue.qsize()

        await download_queue.put({
            "url": target_url,
            "msg": msg,
            "user_id": user_id,
            "format_type": "alac"
        })

        return web.json_response({
            "status": "ok",
            "message": f"Queued at position #{position + 1}. Live progress is updating in your Telegram chat!",
            "user_id": user_id,
            "position": position + 1
        })

    except Exception as e:
        logger.error(f"Error requesting download for user {user_id}: {e}")
        return web.json_response({"error": f"Failed to send request to Telegram: {str(e)}"}, status=500)


@routes.get("/api/artist/{artist_id}")
async def get_artist_detail(request: web.Request):
    """
    Returns full artist profile, artwork, categorized discography, and Vault DB coverage metrics.
    """
    artist_id = request.match_info.get("artist_id", "").strip()
    if not artist_id:
        raise web.HTTPBadRequest(text="Artist ID required")

    try:
        url = f"https://music.apple.com/us/artist/artist/{artist_id}" if artist_id.isdigit() else artist_id
        meta = await gamdlHelpUrl.get_artist_metadata(url)
        artist_name = meta.get("name", "Unknown Artist")

        # Query local database tracks by artist to compute vault coverage
        async with async_session() as session:
            stmt = select(func.count()).select_from(Tracks).where(col(Tracks.artist).ilike(f"%{artist_name}%"))
            db_tracks_res = await session.exec(stmt)
            vault_track_count = db_tracks_res.one() or 0

        meta["vault_track_count"] = vault_track_count
        return web.json_response(meta)

    except Exception as e:
        logger.error(f"Error fetching artist detail for {artist_id}: {e}")
        return web.json_response({"error": str(e)}, status=500)


@routes.get("/api/album/{album_id}")
async def get_album_detail(request: web.Request):
    """
    Returns full album details and tracklist cross-referenced with local database for downloads.
    """
    album_id = request.match_info.get("album_id", "").strip()
    if not album_id:
        raise web.HTTPBadRequest(text="Album ID required")

    try:
        url = f"https://music.apple.com/us/album/album/{album_id}" if album_id.isdigit() else album_id
        meta = await gamdlHelpUrl.get_album_metadata(url)

        tracks = meta.get("tracks", [])
        song_ids_to_check = [str(t["song_id"]) for t in tracks if t.get("song_id")]
        isrcs_to_check = [str(t["isrc"]) for t in tracks if t.get("isrc")]

        # Cross-reference with database
        db_map = {}
        if song_ids_to_check or isrcs_to_check:
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

        available_count = 0
        for tr in tracks:
            key1 = str(tr.get("song_id"))
            key2 = str(tr.get("isrc"))
            tr["is_available"] = False
            tr["download_url"] = None
            tr["stream_url"] = None
            tr["bot_request_cmd"] = f"/download {tr.get('url', '')}"

            if key1 in db_map:
                tr["is_available"] = db_map[key1]["is_available"]
                fmt = db_map[key1]["format"]
                sid = db_map[key1]["song_id"]
                tr["download_url"] = f"/download/{fmt}/{sid}"
                tr["stream_url"] = f"/stream/{fmt}/{sid}"
                if tr["is_available"]:
                    available_count += 1
            elif key2 in db_map:
                tr["is_available"] = db_map[key2]["is_available"]
                fmt = db_map[key2]["format"]
                sid = db_map[key2]["song_id"]
                tr["download_url"] = f"/download/{fmt}/{sid}"
                tr["stream_url"] = f"/stream/{fmt}/{sid}"
                if tr["is_available"]:
                    available_count += 1

        meta["available_track_count"] = available_count
        return web.json_response(meta)

    except Exception as e:
        logger.error(f"Error fetching album detail for {album_id}: {e}")
        return web.json_response({"error": str(e)}, status=500)


@routes.get("/api/song/{song_id}/lyrics")
async def get_song_lyrics(request: web.Request):
    """
    Fetches Apple Music TTML lyrics for a song and parses it into 4 ecosystem formats:
    Synced LRC (.lrc), Plain Text (.txt), Raw TTML XML, and Synced JSON.
    """
    song_id = request.match_info.get("song_id", "").strip()
    if not song_id:
        raise web.HTTPBadRequest(text="Song ID required")

    try:
        api = await gamdlHelpUrl.get_api()
        song = await api.get_song(song_id)
        if not song or "data" not in song or not song["data"]:
            return web.json_response({"has_lyrics": False, "formats": None, "message": "Song not found"})

        song_data = song["data"][0]
        attrs = song_data.get("attributes", {})
        rel = song_data.get("relationships", {})
        lyrics_rel = rel.get("lyrics", {}).get("data", [])

        if not lyrics_rel:
            return web.json_response({
                "song_id": song_id,
                "title": attrs.get("name", "Unknown Title"),
                "artist": attrs.get("artistName", "Unknown Artist"),
                "has_lyrics": False,
                "formats": None
            })

        ttml_xml = lyrics_rel[0].get("attributes", {}).get("ttml", "")
        parsed_lyrics = parse_ttml_lyrics(ttml_xml)

        return web.json_response({
            "song_id": song_id,
            "title": attrs.get("name", "Unknown Title"),
            "artist": attrs.get("artistName", "Unknown Artist"),
            "album": attrs.get("albumName", "Unknown Album"),
            "artwork": gamdlHelpUrl.get_artwork_url(attrs.get("artwork"), size=600),
            "has_lyrics": True,
            "formats": parsed_lyrics
        })

    except Exception as e:
        logger.error(f"Error fetching lyrics for song {song_id}: {e}")
        return web.json_response({"has_lyrics": False, "error": str(e)}, status=500)


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
        song_url = track.url or f"https://music.apple.com/song/{song_id}"
        b64 = base64.urlsafe_b64encode(song_url.encode('utf-8')).decode('utf-8').rstrip('=')
        deeplink = f"https://t.me/applemusicdw_bot?start=dl_{b64}"
        logger.info(f"Track {song_id} not cached. Redirecting browser download request to Telegram Bot deep-link: {deeplink}")
        raise web.HTTPFound(location=deeplink)

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
