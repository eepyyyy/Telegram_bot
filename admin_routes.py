import datetime
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Optional, List, Dict, Any
from pathlib import Path

import aiohttp
from aiohttp import web
from sqlmodel import select, func, or_, col, desc

import bot_control
import database
import gamdlHelpUrl
from database import Tracks, AACTracks, AtmosTracks, MVTracks, Albums, User, DownloadHistory, async_session
from queues import (
    active_tasks,
    get_queue_stats,
    clear_queue,
    user_locks,
    user_pending_jobs,
    user_in_queue,
    download_queue,
    lossless_queue,
    aac_queue,
    atmos_queue,
    mv_queue,
)

logger = logging.getLogger("admin.routes")
admin_routes = web.RouteTableDef()

# Auth config
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "eepyadmin123")
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(32))

# Active admin tokens (token -> expiry timestamp)
active_tokens: dict[str, float] = {}


def generate_token() -> str:
    timestamp = str(time.time())
    random_part = secrets.token_hex(16)
    signature = hmac.new(
        JWT_SECRET.encode(),
        f"{timestamp}:{random_part}".encode(),
        hashlib.sha256,
    ).hexdigest()
    token = f"{timestamp}.{random_part}.{signature}"
    # Token valid for 7 days
    active_tokens[token] = time.time() + 7 * 86400
    return token


def verify_token(token: Optional[str]) -> bool:
    if not token:
        return False
    # Check Bearer prefix if present
    if token.startswith("Bearer "):
        token = token[7:].strip()

    expiry = active_tokens.get(token)
    if not expiry or time.time() > expiry:
        # Cleanup expired token
        active_tokens.pop(token, None)
        return False
    return True


def require_auth(handler):
    """Decorator to require Bearer token for admin endpoints."""
    async def wrapper(request: web.Request):
        # Handle CORS preflight directly
        if request.method == "OPTIONS":
            return add_cors(web.Response(status=204))

        auth_header = request.headers.get("Authorization", "")
        # Also check ?token= query parameter for WebSocket/SSE if needed
        query_token = request.query.get("token", "")
        token = auth_header or query_token

        if not verify_token(token):
            return add_cors(
                web.json_response({"error": "Unauthorized", "message": "Invalid or expired admin token"}, status=401)
            )
        response = await handler(request)
        return add_cors(response)
    return wrapper


def add_cors(response: web.StreamResponse) -> web.StreamResponse:
    """Appends CORS headers for Cloudflare Pages / external domain hosting."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
    return response


# -------------------------------------------------------------
# OPTIONS Handler for CORS Preflight
# -------------------------------------------------------------
@admin_routes.options("/api/admin/{tail:.*}")
async def handle_options(request: web.Request):
    return add_cors(web.Response(status=204))


# -------------------------------------------------------------
# 1. Auth Endpoint
# -------------------------------------------------------------
@admin_routes.post("/api/admin/login")
async def admin_login(request: web.Request):
    try:
        data = await request.json()
    except Exception:
        return add_cors(web.json_response({"error": "Invalid JSON body"}, status=400))

    password = data.get("password", "").strip()
    if not password:
        return add_cors(web.json_response({"error": "Password required"}, status=400))

    # Secure constant-time comparison
    if not hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode()):
        logger.warning(f"[Admin Auth] Failed login attempt from {request.remote}")
        return add_cors(web.json_response({"error": "Invalid admin password"}, status=401))

    token = generate_token()
    logger.info(f"[Admin Auth] Successful login from {request.remote}")
    return add_cors(web.json_response({
        "success": True,
        "token": token,
        "expires_in": 7 * 86400,
        "server_time": datetime.datetime.now().isoformat(),
    }))


# -------------------------------------------------------------
# 2. Real-time Status & Health
# -------------------------------------------------------------
@admin_routes.get("/api/admin/status")
@require_auth
async def get_bot_status(request: web.Request):
    sys_stats = bot_control.get_system_stats()
    q_stats = get_queue_stats()

    return web.json_response({
        "is_paused": bot_control.is_bot_paused,
        "maintenance_mode": bot_control.maintenance_mode,
        "maintenance_message": bot_control.maintenance_message,
        "active_downloads_count": len(active_tasks),
        "queues": q_stats,
        "system": sys_stats,
        "server_time": datetime.datetime.now().isoformat(),
    })


# -------------------------------------------------------------
# 3. Bot Controls (Pause, Resume, Maintenance)
# -------------------------------------------------------------
@admin_routes.post("/api/admin/control")
@require_auth
async def bot_control_action(request: web.Request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    action = data.get("action", "").lower()

    if action == "pause":
        paused = bot_control.set_pause_state(True)
        return web.json_response({"success": True, "is_paused": paused, "message": "Bot download queues paused."})

    elif action == "resume":
        paused = bot_control.set_pause_state(False)
        return web.json_response({"success": True, "is_paused": paused, "message": "Bot download queues resumed."})

    elif action == "toggle_pause":
        paused = bot_control.set_pause_state(not bot_control.is_bot_paused)
        return web.json_response({"success": True, "is_paused": paused, "message": f"Bot queues {'paused' if paused else 'resumed'}."})

    elif action == "set_maintenance":
        enabled = bool(data.get("enabled", False))
        msg = data.get("message")
        m_enabled, m_msg = bot_control.set_maintenance_mode(enabled, msg)
        return web.json_response({
            "success": True,
            "maintenance_mode": m_enabled,
            "maintenance_message": m_msg,
        })

    return web.json_response({"error": f"Unknown action: {action}"}, status=400)


# -------------------------------------------------------------
# 4. Active Downloads Telemetry
# -------------------------------------------------------------
@admin_routes.get("/api/admin/active-downloads")
@require_auth
async def get_active_downloads(request: web.Request):
    downloads = []
    now = time.time()

    for task_id, task in list(active_tasks.items()):
        start_time = task.get("start_time")
        start_ts = None
        duration = 0
        if isinstance(start_time, datetime.datetime):
            start_ts = start_time.isoformat()
            duration = int((datetime.datetime.now(datetime.timezone.utc) - start_time).total_seconds())
        elif isinstance(start_time, (int, float)):
            start_ts = datetime.datetime.fromtimestamp(start_time).isoformat()
            duration = int(now - start_time)

        downloads.append({
            "task_id": task_id,
            "user_id": task.get("user_id"),
            "track_title": task.get("track_title") or "Unknown Track",
            "artist": task.get("artist") or "Unknown Artist",
            "album_name": task.get("album_name") or task.get("album"),
            "url": task.get("url"),
            "format": task.get("format", "alac").upper(),
            "status": task.get("status", "downloading"),
            "progress": task.get("progress", 0),
            "cancelled": bool(task.get("cancelled", False)),
            "start_time": start_ts,
            "duration_seconds": max(0, duration),
        })

    return web.json_response({
        "active_downloads": downloads,
        "count": len(downloads),
    })


# -------------------------------------------------------------
# 5. Cancel Task & Terminate Subprocess
# -------------------------------------------------------------
@admin_routes.post("/api/admin/cancel-task")
@require_auth
async def cancel_task_endpoint(request: web.Request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    task_id = data.get("task_id", "").strip()
    if not task_id:
        return web.json_response({"error": "task_id required"}, status=400)

    if task_id not in active_tasks:
        return web.json_response({"error": f"Task {task_id} not found in active downloads."}, status=404)

    task = active_tasks[task_id]
    task["cancelled"] = True

    # Kill running subprocess if available
    proc = task.get("process")
    if proc:
        try:
            proc.kill()
            logger.info(f"[Admin Control] Killed subprocess for task {task_id}")
        except Exception as e:
            logger.warning(f"[Admin Control] Could not kill process for task {task_id}: {e}")

    # Clear user in-queue lock
    user_id = task.get("user_id")
    if user_id:
        user_in_queue.discard(user_id)
        user_pending_jobs.pop(user_id, None)
        user_locks.pop(user_id, None)

    active_tasks.pop(task_id, None)
    return web.json_response({"success": True, "message": f"Task {task_id} cancelled and terminated."})


# -------------------------------------------------------------
# 6. Clear Pending Queues
# -------------------------------------------------------------
@admin_routes.post("/api/admin/clear-queue")
@require_auth
async def clear_queue_endpoint(request: web.Request):
    try:
        data = await request.json()
    except Exception:
        data = {}

    queue_type = data.get("queue_type", "all").lower()
    removed_count = clear_queue(queue_type)

    logger.info(f"[Admin Control] Cleared queue '{queue_type}', removed {removed_count} jobs.")
    return web.json_response({
        "success": True,
        "queue_type": queue_type,
        "removed_jobs": removed_count,
        "new_queue_stats": get_queue_stats(),
    })


# -------------------------------------------------------------
# 7. Comprehensive Database Metrics
# -------------------------------------------------------------
@admin_routes.get("/api/admin/stats")
@require_auth
async def get_db_stats(request: web.Request):
    async with async_session() as session:
        # Tracks count
        alac_cnt = int((await session.exec(select(func.count()).select_from(Tracks))).one() or 0)
        aac_cnt = int((await session.exec(select(func.count()).select_from(AACTracks))).one() or 0)
        atmos_cnt = int((await session.exec(select(func.count()).select_from(AtmosTracks))).one() or 0)
        albums_cnt = int((await session.exec(select(func.count()).select_from(Albums))).one() or 0)

        # Sizes (PostgreSQL func.sum returns Decimal, cast to float)
        alac_sz = float((await session.exec(select(func.sum(Tracks.size)))).one() or 0.0)
        aac_sz = float((await session.exec(select(func.sum(AACTracks.size)))).one() or 0.0)
        atmos_sz = float((await session.exec(select(func.sum(AtmosTracks.size)))).one() or 0.0)

        # Users
        users_cnt = int((await session.exec(select(func.count()).select_from(User))).one() or 0)
        premium_users_cnt = int((await session.exec(select(func.count()).select_from(User).where(User.is_premium == True))).one() or 0)
        
        # Today downloads
        today = datetime.date.today()
        downloads_today = int((await session.exec(select(func.sum(User.downloaded_today)).where(User.last_download == today))).one() or 0)
        total_downloads = int((await session.exec(select(func.sum(User.download_count)))).one() or 0)

    total_tracks = alac_cnt + aac_cnt + atmos_cnt
    total_size_bytes = int(alac_sz + aac_sz + atmos_sz)
    total_size_gb = round(total_size_bytes / (1024 ** 3), 2) if total_size_bytes else 0.0

    return web.json_response({
        "total_tracks": total_tracks,
        "total_albums": albums_cnt,
        "total_users": users_cnt,
        "premium_users": premium_users_cnt,
        "downloads_today": downloads_today,
        "total_downloads": total_downloads,
        "total_size_bytes": total_size_bytes,
        "total_size_gb": total_size_gb,
        "formats": {
            "alac": {"count": alac_cnt, "size_gb": round(alac_sz / (1024 ** 3), 2) if alac_sz else 0.0},
            "aac": {"count": aac_cnt, "size_gb": round(aac_sz / (1024 ** 3), 2) if aac_sz else 0.0},
            "atmos": {"count": atmos_cnt, "size_gb": round(atmos_sz / (1024 ** 3), 2) if atmos_sz else 0.0},
        }
    })


# -------------------------------------------------------------
# 8. User Explorer & Management
# -------------------------------------------------------------
@admin_routes.get("/api/admin/users")
@require_auth
async def get_users_list(request: web.Request):
    page = max(1, int(request.query.get("page", 1)))
    limit = min(100, max(1, int(request.query.get("limit", 20))))
    search = request.query.get("search", "").strip()
    offset = (page - 1) * limit

    async with async_session() as session:
        query = select(User)
        if search:
            if search.isdigit():
                query = query.where(User.user_id == int(search))
        
        # Order by highest download count
        query = query.order_by(desc(User.download_count)).offset(offset).limit(limit)
        results = (await session.exec(query)).all()

        total_users = int((await session.exec(select(func.count()).select_from(User))).one() or 0)

    users_data = [
        {
            "user_id": u.user_id,
            "username": getattr(u, "username", None),
            "first_name": getattr(u, "first_name", None),
            "download_count": u.download_count or 0,
            "downloaded_today": u.downloaded_today or 0,
            "last_download": u.last_download.isoformat() if u.last_download else None,
            "is_premium": bool(u.is_premium),
            "daily_limit": u.daily_limit or 50,
        }
        for u in results
    ]

    return web.json_response({
        "users": users_data,
        "page": page,
        "limit": limit,
        "total": total_users,
    })


@admin_routes.post("/api/admin/users/{user_id}/premium")
@require_auth
async def toggle_user_premium(request: web.Request):
    user_id_str = request.match_info.get("user_id")
    if not user_id_str or not user_id_str.isdigit():
        return web.json_response({"error": "Invalid user_id"}, status=400)

    user_id = int(user_id_str)
    try:
        data = await request.json()
    except Exception:
        data = {}

    is_premium = bool(data.get("is_premium", True))
    daily_limit = int(data.get("daily_limit", 100 if is_premium else 20))

    async with async_session() as session:
        statement = select(User).where(User.user_id == user_id)
        user = (await session.exec(statement)).first()
        if not user:
            return web.json_response({"error": "User not found"}, status=404)

        user.is_premium = is_premium
        user.daily_limit = daily_limit
        session.add(user)
        await session.commit()
        await session.refresh(user)

    return web.json_response({
        "success": True,
        "user_id": user.user_id,
        "is_premium": user.is_premium,
        "daily_limit": user.daily_limit,
    })


# -------------------------------------------------------------
# 9. In-Memory Real-time Log Stream
# -------------------------------------------------------------
@admin_routes.get("/api/admin/logs")
@require_auth
async def get_logs(request: web.Request):
    level = request.query.get("level", "ALL").upper()
    search = request.query.get("search", "").lower()
    limit = min(500, max(10, int(request.query.get("limit", 200))))

    logs = list(bot_control.log_buffer)

    if level != "ALL":
        logs = [entry for entry in logs if entry.get("level") == level]

    if search:
        logs = [
            entry for entry in logs
            if search in entry.get("message", "").lower()
            or search in entry.get("logger", "").lower()
        ]

    # Return newest logs up to limit
    return web.json_response({
        "logs": logs[-limit:],
        "total_buffered": len(bot_control.log_buffer),
        "returned": len(logs[-limit:]),
    })


# -------------------------------------------------------------
# 10. Recent Downloads History & Telemetry
# -------------------------------------------------------------
@admin_routes.get("/api/admin/recent-downloads")
@require_auth
async def get_recent_downloads(request: web.Request):
    page = max(1, int(request.query.get("page", 1)))
    limit = min(100, max(1, int(request.query.get("limit", 25))))
    format_filter = request.query.get("format", "all").lower().strip()
    cached_filter = request.query.get("cached", "all").lower().strip()
    search = request.query.get("search", "").strip()
    offset = (page - 1) * limit

    async with async_session() as session:
        # Base query
        query = select(DownloadHistory)

        # Filters
        if format_filter and format_filter != "all":
            query = query.where(DownloadHistory.format_type == format_filter)

        if cached_filter == "true":
            query = query.where(DownloadHistory.is_cached == True)
        elif cached_filter == "false":
            query = query.where(DownloadHistory.is_cached == False)

        if search:
            if search.isdigit():
                query = query.where(
                    or_(
                        DownloadHistory.user_id == int(search),
                        DownloadHistory.song_id == search,
                    )
                )
            else:
                query = query.where(DownloadHistory.song_id.ilike(f"%{search}%"))

        # Order by newest
        query = query.order_by(desc(DownloadHistory.downloaded_at)).offset(offset).limit(limit)
        history_records = (await session.exec(query)).all()

        # Total count query for pagination
        count_query = select(func.count()).select_from(DownloadHistory)
        if format_filter and format_filter != "all":
            count_query = count_query.where(DownloadHistory.format_type == format_filter)
        if cached_filter == "true":
            count_query = count_query.where(DownloadHistory.is_cached == True)
        elif cached_filter == "false":
            count_query = count_query.where(DownloadHistory.is_cached == False)
        if search:
            if search.isdigit():
                count_query = count_query.where(
                    or_(
                        DownloadHistory.user_id == int(search),
                        DownloadHistory.song_id == search,
                    )
                )
            else:
                count_query = count_query.where(DownloadHistory.song_id.ilike(f"%{search}%"))

        total_records = int((await session.exec(count_query)).one() or 0)

        # Metrics: Overall cache hit rate
        total_downloads = int((await session.exec(select(func.count()).select_from(DownloadHistory))).one() or 0)
        cached_downloads = int((await session.exec(select(func.count()).select_from(DownloadHistory).where(DownloadHistory.is_cached == True))).one() or 0)
        cache_hit_rate = round((cached_downloads / total_downloads * 100), 1) if total_downloads > 0 else 0.0

        # Collect unique song_ids and user_ids to bulk lookup metadata
        song_ids = [h.song_id for h in history_records if h.song_id]
        user_ids = list({h.user_id for h in history_records if h.user_id})

        # Map metadata from Tracks / AACTracks / AtmosTracks / MVTracks
        track_map = {}
        if song_ids:
            # Check Tracks (ALAC)
            alac_stmt = select(Tracks).where(col(Tracks.song_id).in_(song_ids))
            for t in (await session.exec(alac_stmt)).all():
                track_map[t.song_id] = {
                    "title": t.title,
                    "artist": t.artist,
                    "album": t.album,
                    "artwork": t.artwork,
                    "size": t.size,
                }
            # Check AAC
            aac_stmt = select(AACTracks).where(col(AACTracks.song_id).in_(song_ids))
            for t in (await session.exec(aac_stmt)).all():
                if t.song_id not in track_map:
                    track_map[t.song_id] = {
                        "title": t.title,
                        "artist": t.artist,
                        "album": t.album,
                        "artwork": t.artwork,
                        "size": t.size,
                    }
            # Check Atmos
            atmos_stmt = select(AtmosTracks).where(col(AtmosTracks.song_id).in_(song_ids))
            for t in (await session.exec(atmos_stmt)).all():
                if t.song_id not in track_map:
                    track_map[t.song_id] = {
                        "title": t.title,
                        "artist": t.artist,
                        "album": t.album,
                        "artwork": t.artwork,
                        "size": t.size,
                    }
            # Check MV
            mv_stmt = select(MVTracks).where(col(MVTracks.song_id).in_(song_ids))
            for t in (await session.exec(mv_stmt)).all():
                if t.song_id not in track_map:
                    track_map[t.song_id] = {
                        "title": t.title,
                        "artist": t.artist,
                        "album": t.album,
                        "artwork": t.artwork,
                        "size": t.size,
                    }

        # Map users
        user_map = {}
        if user_ids:
            u_stmt = select(User).where(col(User.user_id).in_(user_ids))
            for u in (await session.exec(u_stmt)).all():
                user_map[u.user_id] = {
                    "username": getattr(u, "username", None),
                    "first_name": getattr(u, "first_name", None),
                    "is_premium": bool(u.is_premium),
                }

    # Format result payload
    downloads_data = []
    for h in history_records:
        meta = track_map.get(h.song_id, {})
        u_info = user_map.get(h.user_id, {})
        downloads_data.append({
            "id": h.id,
            "user_id": h.user_id,
            "username": u_info.get("username"),
            "first_name": u_info.get("first_name"),
            "is_premium": u_info.get("is_premium", False),
            "song_id": h.song_id,
            "title": meta.get("title") or (f"Track {h.song_id}" if h.song_id else "Unknown Track"),
            "artist": meta.get("artist") or "Unknown Artist",
            "album": meta.get("album"),
            "artwork": meta.get("artwork"),
            "format_type": (h.format_type or "alac").upper(),
            "size": h.size or meta.get("size") or 0,
            "is_cached": bool(h.is_cached),
            "downloaded_at": h.downloaded_at.isoformat() if h.downloaded_at else None,
        })

    return web.json_response({
        "downloads": downloads_data,
        "total": total_records,
        "page": page,
        "limit": limit,
        "cache_hit_rate": cache_hit_rate,
        "total_downloads": total_downloads,
        "cached_downloads": cached_downloads,
    })


# -------------------------------------------------------------
# 11. Artist Catalog Search & Discography Coverage
# -------------------------------------------------------------
@admin_routes.get("/api/admin/artist/search")
@require_auth
async def search_artist(request: web.Request):
    q = request.query.get("q", "").strip()
    if not q:
        return web.json_response({"artists": []})

    # If Apple Music URL is passed directly
    if "music.apple.com" in q:
        try:
            meta = await gamdlHelpUrl.get_artist_metadata(q)
            return web.json_response({
                "artists": [{
                    "id": str(meta.get("artist_id", "")),
                    "name": meta.get("name", "Unknown Artist"),
                    "url": meta.get("url", q),
                    "artwork": meta.get("artwork"),
                    "genres": meta.get("genres", []),
                }]
            })
        except Exception as e:
            logger.warning(f"Error parsing direct artist URL {q}: {e}")

    # Search via iTunes / Apple Music search API
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://itunes.apple.com/search?term={q}&entity=musicArtist&limit=15"
            async with session.get(url) as resp:
                data = await resp.json(content_type=None)
                results = []
                for item in data.get("results", []):
                    results.append({
                        "id": str(item.get("artistId", "")),
                        "name": item.get("artistName", ""),
                        "url": item.get("artistLinkUrl", ""),
                        "artwork": None,
                        "genres": [item.get("primaryGenreName")] if item.get("primaryGenreName") else [],
                    })
                return web.json_response({"artists": results})
    except Exception as e:
        logger.error(f"Error searching artists: {e}")
        return web.json_response({"artists": [], "error": str(e)}, status=500)


@admin_routes.get("/api/admin/artist/details")
@require_auth
async def get_artist_details_for_cache(request: web.Request):
    artist_input = request.query.get("artist", "").strip()
    if not artist_input:
        return web.json_response({"error": "artist parameter (ID or URL) required"}, status=400)

    url = (
        f"https://music.apple.com/us/artist/artist/{artist_input}"
        if artist_input.isdigit()
        else artist_input
    )

    try:
        meta = await gamdlHelpUrl.get_artist_metadata(url)
        artist_name = meta.get("name", "Unknown Artist")
        categories = meta.get("categories", {})

        # Collect all album names or URLs to check cache coverage in local DB
        all_album_names = []
        for cat_name, albums in categories.items():
            for alb in albums:
                if alb.get("name"):
                    all_album_names.append(alb["name"].strip().lower())

        cached_albums_set = set()
        async with async_session() as session:
            if all_album_names:
                stmt = select(Albums.album).where(func.lower(Albums.album).in_(all_album_names))
                db_albs = (await session.exec(stmt)).all()
                cached_albums_set = {a.strip().lower() for a in db_albs if a}

            # Also query total tracks cached for this artist in Tracks, AACTracks, AtmosTracks
            alac_tracks = int((await session.exec(select(func.count()).select_from(Tracks).where(col(Tracks.artist).ilike(f"%{artist_name}%")))).one() or 0)
            aac_tracks = int((await session.exec(select(func.count()).select_from(AACTracks).where(col(AACTracks.artist).ilike(f"%{artist_name}%")))).one() or 0)
            atmos_tracks = int((await session.exec(select(func.count()).select_from(AtmosTracks).where(col(AtmosTracks.artist).ilike(f"%{artist_name}%")))).one() or 0)

        # Enrich each release with is_cached status
        enriched_categories = {}
        total_releases = 0
        total_cached_releases = 0

        for cat_name, albums in categories.items():
            enriched_categories[cat_name] = []
            for alb in albums:
                total_releases += 1
                name_clean = (alb.get("name") or "").strip().lower()
                is_cached = name_clean in cached_albums_set
                if is_cached:
                    total_cached_releases += 1

                enriched_categories[cat_name].append({
                    "name": alb.get("name"),
                    "release_date": alb.get("release_date"),
                    "track_count": alb.get("track_count"),
                    "url": alb.get("url"),
                    "is_cached": is_cached,
                })

        return web.json_response({
            "artist_id": meta.get("artist_id"),
            "name": artist_name,
            "url": meta.get("url", url),
            "storefront": meta.get("storefront", "us"),
            "artwork": meta.get("artwork"),
            "genres": meta.get("genres", []),
            "categories": enriched_categories,
            "total_releases": total_releases,
            "total_cached_releases": total_cached_releases,
            "coverage_percent": round((total_cached_releases / total_releases * 100), 1) if total_releases > 0 else 0,
            "cached_tracks": {
                "alac": alac_tracks,
                "aac": aac_tracks,
                "atmos": atmos_tracks,
                "total": alac_tracks + aac_tracks + atmos_tracks,
            },
        })

    except Exception as e:
        logger.error(f"Error fetching artist details: {e}")
        return web.json_response({"error": str(e)}, status=500)


# -------------------------------------------------------------
# 12. Enqueue Bulk Artist Releases to Bot Cache Queue
# -------------------------------------------------------------
@admin_routes.post("/api/admin/artist/cache")
@require_auth
async def bulk_cache_artist_releases(request: web.Request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    albums = data.get("albums", [])
    format_type = data.get("format", "alac").lower().strip()
    admin_user_id = data.get("admin_user_id")

    if not albums:
        return web.json_response({"error": "No albums provided to cache"}, status=400)

    # Use a dummy system user_id if none provided
    system_user_id = int(admin_user_id) if admin_user_id and str(admin_user_id).isdigit() else 999999999

    queued_jobs = 0
    formats_to_queue = []
    if format_type in ("all", "both"):
        formats_to_queue = ["alac", "aac", "atmos"]
    elif format_type == "aac":
        formats_to_queue = ["aac"]
    elif format_type == "atmos":
        formats_to_queue = ["atmos"]
    else:
        formats_to_queue = ["alac"]

    for alb in albums:
        url = alb.get("url")
        if not url:
            continue

        for fmt in formats_to_queue:
            payload = {
                "url": url,
                "user_id": system_user_id,
                "format_type": fmt,
                "is_admin_cache": True,
                "album_name": alb.get("name"),
            }

            if fmt == "aac":
                await aac_queue.put(payload)
            elif fmt == "atmos":
                await atmos_queue.put(payload)
            else:
                await download_queue.put(payload)

            queued_jobs += 1

    logger.info(f"[Admin Cacher] Queued {queued_jobs} release jobs for formats {formats_to_queue}.")
    return web.json_response({
        "success": True,
        "queued_jobs": queued_jobs,
        "formats": formats_to_queue,
        "message": f"Successfully queued {len(albums)} release(s) ({queued_jobs} download jobs) for background caching.",
    })
