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
from sqlmodel import select, func, or_, and_, col, desc

import bot_control
import database
import gamdlHelpUrl
from database import Tracks, AACTracks, AtmosTracks, MVTracks, Albums, User, DownloadHistory, async_session
from queues import (
    active_tasks,
    get_queue_stats,
    clear_queue,
    cancel_all_active_tasks,
    user_locks,
    user_pending_jobs,
    user_in_queue,
    aac_locks,
    aac_pending_jobs,
    aac_in_queue,
    atmos_locks,
    atmos_pending_jobs,
    atmos_in_queue,
    lossless_locks,
    lossless_pending_jobs,
    lossless_in_queue,
    mv_locks,
    mv_pending_jobs,
    mv_in_queue,
    download_queue,
    lossless_queue,
    aac_queue,
    atmos_queue,
    mv_queue,
)

logger = logging.getLogger("admin.routes")
admin_routes = web.RouteTableDef()

# Auth config
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "user")
JWT_SECRET = os.getenv("JWT_SECRET", "tbot_admin_jwt_secret_key_stable")

# Active admin tokens (token -> expiry timestamp)
active_tokens: dict[str, float] = {}


def generate_token() -> str:
    timestamp = str(int(time.time()))
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

    # 1. Fast in-memory check
    expiry = active_tokens.get(token)
    if expiry:
        if time.time() <= expiry:
            return True
        active_tokens.pop(token, None)
        return False

    # 2. Stateless cryptographic verification (survives bot restarts!)
    try:
        parts = token.split(".")
        if len(parts) == 3:
            ts_str, random_part, signature = parts
            ts = float(ts_str)
            # Valid for 7 days
            if time.time() - ts <= 7 * 86400:
                expected_sig = hmac.new(
                    JWT_SECRET.encode(),
                    f"{ts_str}:{random_part}".encode(),
                    hashlib.sha256,
                ).hexdigest()
                if hmac.compare_digest(signature, expected_sig):
                    # Cache valid token in memory
                    active_tokens[token] = ts + 7 * 86400
                    return True
    except Exception:
        pass

    return False


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

    elif action == "restart":
        logger.info("[Admin Control] Bot restart requested via /api/admin/control.")
        async def _do_restart():
            await asyncio.sleep(1)
            try:
                cancel_all_active_tasks()
            except Exception as e:
                logger.warning(f"Error cancelling tasks on restart: {e}")
            logger.info("[Admin Control] Exiting process to trigger restart...")
            os._exit(0)

        asyncio.create_task(_do_restart())
        return web.json_response({
            "success": True,
            "message": "Bot restart initiated. The bot process is restarting."
        })

    elif action == "backfill_zip_sizes":
        logger.info("[Admin Control] ZIP size backfill requested via /api/admin/control.")
        import crud
        asyncio.create_task(crud.backfill_missing_zip_sizes(bot_control.bot_instance))
        return web.json_response({
            "success": True,
            "message": "ZIP file size backfill initiated in background."
        })

    return web.json_response({"error": f"Unknown action: {action}"}, status=400)


@admin_routes.post("/api/admin/restart")
@require_auth
async def restart_bot_endpoint(request: web.Request):
    logger.info("[Admin Control] Bot restart requested via /api/admin/restart.")
    async def _do_restart():
        await asyncio.sleep(1)
        try:
            cancel_all_active_tasks()
        except Exception as e:
            logger.warning(f"Error cancelling tasks on restart: {e}")
        logger.info("[Admin Control] Exiting process to trigger restart...")
        os._exit(0)

    asyncio.create_task(_do_restart())
    return web.json_response({
        "success": True,
        "message": "Bot restart initiated. The bot process is restarting."
    })


@admin_routes.post("/api/admin/backfill-zip-sizes")
@require_auth
async def backfill_zip_sizes_endpoint(request: web.Request):
    logger.info("[Admin Control] ZIP size backfill requested via /api/admin/backfill-zip-sizes.")
    import crud
    asyncio.create_task(crud.backfill_missing_zip_sizes(bot_control.bot_instance))
    return web.json_response({
        "success": True,
        "message": "ZIP file size backfill initiated in background."
    })


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

    # Notify Telegram status message if available
    status_msg = task.get("status_msg")
    if status_msg:
        try:
            await status_msg.edit_text("❌ <b>Task was cancelled by administrator.</b>", parse_mode="HTML")
        except Exception:
            pass

    # Clear user in-queue locks across all formats
    user_id = task.get("user_id")
    if user_id:
        user_in_queue.discard(user_id)
        user_pending_jobs.pop(user_id, None)
        user_locks.pop(user_id, None)
        aac_in_queue.discard(user_id)
        aac_pending_jobs.pop(user_id, None)
        aac_locks.pop(user_id, None)
        atmos_in_queue.discard(user_id)
        atmos_pending_jobs.pop(user_id, None)
        atmos_locks.pop(user_id, None)
        lossless_in_queue.discard(user_id)
        lossless_pending_jobs.pop(user_id, None)
        lossless_locks.pop(user_id, None)
        mv_in_queue.discard(user_id)
        mv_pending_jobs.pop(user_id, None)
        mv_locks.pop(user_id, None)

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
    cancel_active = bool(data.get("cancel_active", True))
    result = clear_queue(queue_type, cancel_active=cancel_active)
    removed_jobs = result["removed_jobs"] if isinstance(result, dict) else result
    cancelled_active = result.get("cancelled_active", 0) if isinstance(result, dict) else 0

    logger.info(f"[Admin Control] Cleared queue '{queue_type}', removed {removed_jobs} jobs, cancelled {cancelled_active} active (cancel_active={cancel_active}).")
    return web.json_response({
        "success": True,
        "queue_type": queue_type,
        "removed_jobs": removed_jobs,
        "cancelled_active": cancelled_active,
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
        mv_cnt = int((await session.exec(select(func.count()).select_from(MVTracks))).one() or 0)
        albums_cnt = int((await session.exec(select(func.count()).select_from(Albums))).one() or 0)

        # Sizes (PostgreSQL func.sum returns Decimal, cast to float)
        alac_sz = float((await session.exec(select(func.sum(Tracks.size)))).one() or 0.0)
        aac_sz = float((await session.exec(select(func.sum(AACTracks.size)))).one() or 0.0)
        atmos_sz = float((await session.exec(select(func.sum(AtmosTracks.size)))).one() or 0.0)
        mv_sz = float((await session.exec(select(func.sum(MVTracks.size)))).one() or 0.0)

        # Album ZIP sizes
        alac_zip_sz = float((await session.exec(select(func.sum(Albums.alac_zip_size)))).one() or 0.0)
        aac_zip_sz = float((await session.exec(select(func.sum(Albums.aac_zip_size)))).one() or 0.0)
        atmos_zip_sz = float((await session.exec(select(func.sum(Albums.atmos_zip_size)))).one() or 0.0)
        total_zip_sz = alac_zip_sz + aac_zip_sz + atmos_zip_sz

        # Album ZIP counts
        alac_zip_cnt = int((await session.exec(select(func.count()).select_from(Albums).where(Albums.alac_zip_file_id.is_not(None)))).one() or 0)
        aac_zip_cnt = int((await session.exec(select(func.count()).select_from(Albums).where(Albums.aac_zip_file_id.is_not(None)))).one() or 0)
        atmos_zip_cnt = int((await session.exec(select(func.count()).select_from(Albums).where(Albums.atmos_zip_file_id.is_not(None)))).one() or 0)
        total_zip_cnt = alac_zip_cnt + aac_zip_cnt + atmos_zip_cnt

        total_zip_bytes = int(total_zip_sz)
        total_zip_gb = round(total_zip_sz / (1024 ** 3), 2) if total_zip_sz else 0.0

        # Users
        users_cnt = int((await session.exec(select(func.count()).select_from(User))).one() or 0)
        premium_users_cnt = int((await session.exec(select(func.count()).select_from(User).where(User.is_premium == True))).one() or 0)
        
        # Today downloads
        today = datetime.date.today()
        downloads_today = int((await session.exec(select(func.sum(User.downloaded_today)).where(User.last_download == today))).one() or 0)
        total_downloads = int((await session.exec(select(func.sum(User.download_count)))).one() or 0)

    total_tracks = alac_cnt + aac_cnt + atmos_cnt + mv_cnt
    total_audio_bytes = int(alac_sz + aac_sz + atmos_sz + mv_sz)
    total_size_bytes = int(total_audio_bytes + total_zip_bytes)
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
        "total_zip_size_bytes": total_zip_bytes,
        "total_zip_size_gb": total_zip_gb,
        "total_zip_count": total_zip_cnt,
        "formats": {
            "alac": {
                "count": alac_cnt,
                "size_gb": round(alac_sz / (1024 ** 3), 2) if alac_sz else 0.0,
                "zip_count": alac_zip_cnt,
                "zip_size_gb": round(alac_zip_sz / (1024 ** 3), 2) if alac_zip_sz else 0.0,
            },
            "aac": {
                "count": aac_cnt,
                "size_gb": round(aac_sz / (1024 ** 3), 2) if aac_sz else 0.0,
                "zip_count": aac_zip_cnt,
                "zip_size_gb": round(aac_zip_sz / (1024 ** 3), 2) if aac_zip_sz else 0.0,
            },
            "atmos": {
                "count": atmos_cnt,
                "size_gb": round(atmos_sz / (1024 ** 3), 2) if atmos_sz else 0.0,
                "zip_count": atmos_zip_cnt,
                "zip_size_gb": round(atmos_zip_sz / (1024 ** 3), 2) if atmos_zip_sz else 0.0,
            },
            "mv": {
                "count": mv_cnt,
                "size_gb": round(mv_sz / (1024 ** 3), 2) if mv_sz else 0.0,
            },
            "zips": {
                "count": total_zip_cnt,
                "size_gb": total_zip_gb,
            }
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


# -------------------------------------------------------------
# 12. Album ZIP Files Catalog & Properties Management
# -------------------------------------------------------------
@admin_routes.get("/api/admin/albums")
@require_auth
async def get_albums_endpoint(request: web.Request):
    """
    Returns paginated list of albums with their cached ZIP properties, file IDs, sizes, and GoFile links.
    Supports search (title, artist, album_id) and filter ('all', 'has_zip', 'missing_zip', 'alac', 'aac', 'atmos').
    """
    try:
        page = max(1, int(request.query.get("page", 1)))
    except (ValueError, TypeError):
        page = 1
    try:
        limit = min(100, max(1, int(request.query.get("limit", 20))))
    except (ValueError, TypeError):
        limit = 20

    offset = (page - 1) * limit
    search = request.query.get("search", "").strip()
    filter_type = request.query.get("filter", "all").strip().lower()
    sort_by = request.query.get("sort", "recent").strip().lower()

    async with async_session() as session:
        conditions = []
        if search:
            search_clause = or_(
                Albums.album.ilike(f"%{search}%"),
                Albums.artist.ilike(f"%{search}%"),
                Albums.album_id.ilike(f"%{search}%"),
            )
            conditions.append(search_clause)

        if filter_type == "has_zip":
            conditions.append(
                or_(
                    Albums.alac_zip_file_id.is_not(None),
                    Albums.alac_gofile_url.is_not(None),
                    Albums.aac_zip_file_id.is_not(None),
                    Albums.aac_gofile_url.is_not(None),
                    Albums.atmos_zip_file_id.is_not(None),
                    Albums.atmos_gofile_url.is_not(None),
                )
            )
        elif filter_type == "missing_zip":
            conditions.append(
                and_(
                    Albums.alac_zip_file_id.is_(None),
                    Albums.alac_gofile_url.is_(None),
                    Albums.aac_zip_file_id.is_(None),
                    Albums.aac_gofile_url.is_(None),
                    Albums.atmos_zip_file_id.is_(None),
                    Albums.atmos_gofile_url.is_(None),
                )
            )
        elif filter_type in ("alac", "alac_zip"):
            conditions.append(
                or_(Albums.alac_zip_file_id.is_not(None), Albums.alac_gofile_url.is_not(None))
            )
        elif filter_type in ("aac", "aac_zip"):
            conditions.append(
                or_(Albums.aac_zip_file_id.is_not(None), Albums.aac_gofile_url.is_not(None))
            )
        elif filter_type in ("atmos", "atmos_zip"):
            conditions.append(
                or_(Albums.atmos_zip_file_id.is_not(None), Albums.atmos_gofile_url.is_not(None))
            )

        # Count total records matching criteria
        count_stmt = select(func.count()).select_from(Albums)
        if conditions:
            count_stmt = count_stmt.where(and_(*conditions))
        total_records = int((await session.exec(count_stmt)).one() or 0)

        # Query albums page
        query = select(Albums)
        if conditions:
            query = query.where(and_(*conditions))

        if sort_by == "name":
            query = query.order_by(Albums.album.asc())
        elif sort_by == "artist":
            query = query.order_by(Albums.artist.asc())
        elif sort_by == "size_desc":
            query = query.order_by(
                func.coalesce(Albums.alac_zip_size, Albums.aac_zip_size, Albums.atmos_zip_size, 0).desc()
            )
        else:
            query = query.order_by(Albums.album_id.desc())

        query = query.offset(offset).limit(limit)
        albums_list = (await session.exec(query)).all()

        album_ids = [a.album_id for a in albums_list if a.album_id]

        # Get track counts for these albums
        track_counts = {}
        if album_ids:
            try:
                t_stmt = select(Tracks.album_id, func.count()).where(col(Tracks.album_id).in_(album_ids)).group_by(Tracks.album_id)
                for alb_id, cnt in (await session.exec(t_stmt)).all():
                    track_counts[alb_id] = max(track_counts.get(alb_id, 0), int(cnt))

                aac_t_stmt = select(AACTracks.album_id, func.count()).where(col(AACTracks.album_id).in_(album_ids)).group_by(AACTracks.album_id)
                for alb_id, cnt in (await session.exec(aac_t_stmt)).all():
                    track_counts[alb_id] = max(track_counts.get(alb_id, 0), int(cnt))

                atmos_t_stmt = select(AtmosTracks.album_id, func.count()).where(col(AtmosTracks.album_id).in_(album_ids)).group_by(AtmosTracks.album_id)
                for alb_id, cnt in (await session.exec(atmos_t_stmt)).all():
                    track_counts[alb_id] = max(track_counts.get(alb_id, 0), int(cnt))
            except Exception as te:
                logger.warning(f"Failed to query track counts for albums: {te}")

        # Summary stats across whole database
        alac_zip_cnt = int((await session.exec(select(func.count()).select_from(Albums).where(Albums.alac_zip_file_id.is_not(None)))).one() or 0)
        aac_zip_cnt = int((await session.exec(select(func.count()).select_from(Albums).where(Albums.aac_zip_file_id.is_not(None)))).one() or 0)
        atmos_zip_cnt = int((await session.exec(select(func.count()).select_from(Albums).where(Albums.atmos_zip_file_id.is_not(None)))).one() or 0)
        alac_zip_sz = float((await session.exec(select(func.sum(Albums.alac_zip_size)))).one() or 0.0)
        aac_zip_sz = float((await session.exec(select(func.sum(Albums.aac_zip_size)))).one() or 0.0)
        atmos_zip_sz = float((await session.exec(select(func.sum(Albums.atmos_zip_size)))).one() or 0.0)
        total_zip_sz = alac_zip_sz + aac_zip_sz + atmos_zip_sz

    albums_payload = []
    for alb in albums_list:
        has_alac = bool(alb.alac_zip_file_id or alb.alac_gofile_url)
        has_aac = bool(alb.aac_zip_file_id or alb.aac_gofile_url)
        has_atmos = bool(alb.atmos_zip_file_id or alb.atmos_gofile_url)
        albums_payload.append({
            "album_id": alb.album_id,
            "album": alb.album or "Unknown Album",
            "artist": alb.artist or "Unknown Artist",
            "artwork": alb.artwork,
            "alac_zip_file_id": alb.alac_zip_file_id,
            "alac_zip_size": alb.alac_zip_size,
            "alac_gofile_url": alb.alac_gofile_url,
            "aac_zip_file_id": alb.aac_zip_file_id,
            "aac_zip_size": alb.aac_zip_size,
            "aac_gofile_url": alb.aac_gofile_url,
            "atmos_zip_file_id": alb.atmos_zip_file_id,
            "atmos_zip_size": alb.atmos_zip_size,
            "atmos_gofile_url": alb.atmos_gofile_url,
            "track_count": track_counts.get(alb.album_id, 0),
            "has_alac_zip": has_alac,
            "has_aac_zip": has_aac,
            "has_atmos_zip": has_atmos,
            "has_any_zip": has_alac or has_aac or has_atmos,
        })

    return web.json_response({
        "albums": albums_payload,
        "total": total_records,
        "page": page,
        "limit": limit,
        "summary": {
            "total_with_zip": alac_zip_cnt + aac_zip_cnt + atmos_zip_cnt,
            "alac_zip_count": alac_zip_cnt,
            "alac_zip_size_bytes": int(alac_zip_sz),
            "aac_zip_count": aac_zip_cnt,
            "aac_zip_size_bytes": int(aac_zip_sz),
            "atmos_zip_count": atmos_zip_cnt,
            "atmos_zip_size_bytes": int(atmos_zip_sz),
            "total_zip_size_bytes": int(total_zip_sz),
            "total_zip_size_gb": round(total_zip_sz / (1024 ** 3), 2),
        }
    })


@admin_routes.get("/api/admin/albums/{album_id}")
@require_auth
async def get_single_album_endpoint(request: web.Request):
    """
    Returns full details for a single album, including tracks cached in Tracks, AACTracks, and AtmosTracks.
    """
    album_id = request.match_info.get("album_id", "").strip()
    if not album_id:
        return web.json_response({"error": "Album ID required"}, status=400)

    async with async_session() as session:
        album = (await session.exec(select(Albums).where(Albums.album_id == album_id))).first()
        if not album:
            return web.json_response({"error": f"Album {album_id} not found in database"}, status=404)

        # Collect tracks
        alac_tracks = (await session.exec(select(Tracks).where(Tracks.album_id == album_id))).all()
        aac_tracks = (await session.exec(select(AACTracks).where(AACTracks.album_id == album_id))).all()
        atmos_tracks = (await session.exec(select(AtmosTracks).where(AtmosTracks.album_id == album_id))).all()

        track_map = {}
        for t in alac_tracks:
            sid = t.song_id or t.title
            track_map[sid] = {
                "song_id": t.song_id,
                "title": t.title,
                "artist": t.artist,
                "url": t.url,
                "isrc": t.isrc,
                "artwork": t.artwork,
                "formats": ["ALAC"],
                "alac_file_id": t.file_id,
                "alac_size": t.size,
                "aac_file_id": None,
                "aac_size": None,
                "atmos_file_id": None,
                "atmos_size": None,
            }

        for t in aac_tracks:
            sid = t.song_id or t.title
            if sid in track_map:
                if "AAC" not in track_map[sid]["formats"]:
                    track_map[sid]["formats"].append("AAC")
                track_map[sid]["aac_file_id"] = t.file_id
                track_map[sid]["aac_size"] = t.size
            else:
                track_map[sid] = {
                    "song_id": t.song_id,
                    "title": t.title,
                    "artist": t.artist,
                    "url": t.url,
                    "isrc": t.isrc,
                    "artwork": t.artwork,
                    "formats": ["AAC"],
                    "alac_file_id": None,
                    "alac_size": None,
                    "aac_file_id": t.file_id,
                    "aac_size": t.size,
                    "atmos_file_id": None,
                    "atmos_size": None,
                }

        for t in atmos_tracks:
            sid = t.song_id or t.title
            if sid in track_map:
                if "ATMOS" not in track_map[sid]["formats"]:
                    track_map[sid]["formats"].append("ATMOS")
                track_map[sid]["atmos_file_id"] = t.file_id
                track_map[sid]["atmos_size"] = t.size
            else:
                track_map[sid] = {
                    "song_id": t.song_id,
                    "title": t.title,
                    "artist": t.artist,
                    "url": t.url,
                    "isrc": t.isrc,
                    "artwork": t.artwork,
                    "formats": ["ATMOS"],
                    "alac_file_id": None,
                    "alac_size": None,
                    "aac_file_id": None,
                    "aac_size": None,
                    "atmos_file_id": t.file_id,
                    "atmos_size": t.size,
                }

    return web.json_response({
        "album": {
            "album_id": album.album_id,
            "album": album.album or "Unknown Album",
            "artist": album.artist or "Unknown Artist",
            "artwork": album.artwork,
            "alac_zip_file_id": album.alac_zip_file_id,
            "alac_zip_size": album.alac_zip_size,
            "alac_gofile_url": album.alac_gofile_url,
            "aac_zip_file_id": album.aac_zip_file_id,
            "aac_zip_size": album.aac_zip_size,
            "aac_gofile_url": album.aac_gofile_url,
            "atmos_zip_file_id": album.atmos_zip_file_id,
            "atmos_zip_size": album.atmos_zip_size,
            "atmos_gofile_url": album.atmos_gofile_url,
            "track_count": len(track_map),
        },
        "tracks": list(track_map.values()),
    })


@admin_routes.put("/api/admin/albums/{album_id}")
@require_auth
async def update_album_properties_endpoint(request: web.Request):
    """
    Updates album metadata and ZIP cache properties directly in the database.
    """
    album_id = request.match_info.get("album_id", "").strip()
    if not album_id:
        return web.json_response({"error": "Album ID required"}, status=400)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    async with async_session() as session:
        album = (await session.exec(select(Albums).where(Albums.album_id == album_id))).first()
        if not album:
            return web.json_response({"error": f"Album {album_id} not found in database"}, status=404)

        # Update metadata if present in payload
        if "album" in data:
            album.album = data["album"].strip() if data["album"] else None
        if "artist" in data:
            album.artist = data["artist"].strip() if data["artist"] else None
        if "artwork" in data:
            album.artwork = data["artwork"].strip() if data["artwork"] else None

        # Update ALAC ZIP properties
        if "alac_zip_file_id" in data:
            val = data["alac_zip_file_id"]
            album.alac_zip_file_id = val.strip() if val else None
        if "alac_zip_size" in data:
            val = data["alac_zip_size"]
            album.alac_zip_size = int(val) if val is not None and str(val).isdigit() else None
        if "alac_gofile_url" in data:
            val = data["alac_gofile_url"]
            album.alac_gofile_url = val.strip() if val else None

        # Update AAC ZIP properties
        if "aac_zip_file_id" in data:
            val = data["aac_zip_file_id"]
            album.aac_zip_file_id = val.strip() if val else None
        if "aac_zip_size" in data:
            val = data["aac_zip_size"]
            album.aac_zip_size = int(val) if val is not None and str(val).isdigit() else None
        if "aac_gofile_url" in data:
            val = data["aac_gofile_url"]
            album.aac_gofile_url = val.strip() if val else None

        # Update ATMOS ZIP properties
        if "atmos_zip_file_id" in data:
            val = data["atmos_zip_file_id"]
            album.atmos_zip_file_id = val.strip() if val else None
        if "atmos_zip_size" in data:
            val = data["atmos_zip_size"]
            album.atmos_zip_size = int(val) if val is not None and str(val).isdigit() else None
        if "atmos_gofile_url" in data:
            val = data["atmos_gofile_url"]
            album.atmos_gofile_url = val.strip() if val else None

        session.add(album)
        await session.commit()
        await session.refresh(album)

    logger.info(f"[Admin Albums] Updated album properties for album {album_id}.")
    return web.json_response({
        "success": True,
        "message": f"Album {album_id} properties successfully updated.",
        "album": {
            "album_id": album.album_id,
            "album": album.album,
            "artist": album.artist,
            "artwork": album.artwork,
            "alac_zip_file_id": album.alac_zip_file_id,
            "alac_zip_size": album.alac_zip_size,
            "alac_gofile_url": album.alac_gofile_url,
            "aac_zip_file_id": album.aac_zip_file_id,
            "aac_zip_size": album.aac_zip_size,
            "aac_gofile_url": album.aac_gofile_url,
            "atmos_zip_file_id": album.atmos_zip_file_id,
            "atmos_zip_size": album.atmos_zip_size,
            "atmos_gofile_url": album.atmos_gofile_url,
        }
    })


@admin_routes.post("/api/admin/albums/{album_id}/clear-zip")
@require_auth
async def clear_album_zip_endpoint(request: web.Request):
    """
    Clears the cached ZIP file ID, size, and GoFile URL for a specific format or all formats.
    This forces the bot to re-download and re-package the album fresh on the next user request.
    """
    album_id = request.match_info.get("album_id", "").strip()
    if not album_id:
        return web.json_response({"error": "Album ID required"}, status=400)

    try:
        data = await request.json()
    except Exception:
        data = {}

    fmt = data.get("format", "all").strip().lower()

    async with async_session() as session:
        album = (await session.exec(select(Albums).where(Albums.album_id == album_id))).first()
        if not album:
            return web.json_response({"error": f"Album {album_id} not found in database"}, status=404)

        if fmt in ("alac", "all"):
            album.alac_zip_file_id = None
            album.alac_zip_size = None
            album.alac_gofile_url = None

        if fmt in ("aac", "all"):
            album.aac_zip_file_id = None
            album.aac_zip_size = None
            album.aac_gofile_url = None

        if fmt in ("atmos", "all"):
            album.atmos_zip_file_id = None
            album.atmos_zip_size = None
            album.atmos_gofile_url = None

        session.add(album)
        await session.commit()
        await session.refresh(album)

    logger.info(f"[Admin Albums] Cleared {fmt.upper()} ZIP cache for album {album_id}.")
    return web.json_response({
        "success": True,
        "message": f"Successfully cleared {fmt.upper()} ZIP cache for album {album_id}.",
        "album": {
            "album_id": album.album_id,
            "album": album.album,
            "artist": album.artist,
            "alac_zip_file_id": album.alac_zip_file_id,
            "alac_zip_size": album.alac_zip_size,
            "alac_gofile_url": album.alac_gofile_url,
            "aac_zip_file_id": album.aac_zip_file_id,
            "aac_zip_size": album.aac_zip_size,
            "aac_gofile_url": album.aac_gofile_url,
            "atmos_zip_file_id": album.atmos_zip_file_id,
            "atmos_zip_size": album.atmos_zip_size,
            "atmos_gofile_url": album.atmos_gofile_url,
        }
    })


@admin_routes.delete("/api/admin/albums/{album_id}")
@require_auth
async def delete_album_endpoint(request: web.Request):
    """
    Deletes the album from the albums database table.
    If query param ?delete_tracks=true is passed, also deletes associated cached tracks.
    """
    album_id = request.match_info.get("album_id", "").strip()
    if not album_id:
        return web.json_response({"error": "Album ID required"}, status=400)

    delete_tracks = request.query.get("delete_tracks", "false").lower() in ("true", "1", "yes")

    async with async_session() as session:
        album = (await session.exec(select(Albums).where(Albums.album_id == album_id))).first()
        if not album:
            return web.json_response({"error": f"Album {album_id} not found in database"}, status=404)

        deleted_tracks_count = 0
        if delete_tracks:
            # Delete from Tracks, AACTracks, AtmosTracks
            alac_trs = (await session.exec(select(Tracks).where(Tracks.album_id == album_id))).all()
            for t in alac_trs:
                await session.delete(t)
                deleted_tracks_count += 1

            aac_trs = (await session.exec(select(AACTracks).where(AACTracks.album_id == album_id))).all()
            for t in aac_trs:
                await session.delete(t)
                deleted_tracks_count += 1

            atmos_trs = (await session.exec(select(AtmosTracks).where(AtmosTracks.album_id == album_id))).all()
            for t in atmos_trs:
                await session.delete(t)
                deleted_tracks_count += 1

        await session.delete(album)
        await session.commit()

    logger.info(f"[Admin Albums] Deleted album {album_id} (deleted_tracks={delete_tracks}, count={deleted_tracks_count}).")
    return web.json_response({
        "success": True,
        "message": f"Successfully deleted album {album_id}" + (f" and {deleted_tracks_count} track(s)." if delete_tracks else "."),
    })


@admin_routes.post("/api/admin/albums/{album_id}/verify-zip")
@require_auth
async def verify_album_zip_endpoint(request: web.Request):
    """
    Queries Telegram Bot API to check whether the cached file_id for a given format is still valid.
    If valid, returns Telegram file metadata and updates the size in the database.
    """
    album_id = request.match_info.get("album_id", "").strip()
    if not album_id:
        return web.json_response({"error": "Album ID required"}, status=400)

    try:
        data = await request.json()
    except Exception:
        data = {}

    fmt = data.get("format", "alac").strip().lower()

    async with async_session() as session:
        album = (await session.exec(select(Albums).where(Albums.album_id == album_id))).first()
        if not album:
            return web.json_response({"error": f"Album {album_id} not found in database"}, status=404)

        if fmt == "aac":
            file_id = album.aac_zip_file_id
        elif fmt == "atmos":
            file_id = album.atmos_zip_file_id
        else:
            file_id = album.alac_zip_file_id

        if not file_id:
            return web.json_response({
                "valid": False,
                "error": f"No {fmt.upper()} ZIP file_id is recorded for album {album_id}.",
                "file_id": None
            })

        bot = getattr(bot_control, "bot_instance", None)
        if not bot:
            return web.json_response({
                "valid": False,
                "error": "Telegram Bot instance is not currently active.",
                "file_id": file_id
            })

        try:
            tg_file = await bot.get_file(file_id)
            if tg_file:
                # Update size in database if available
                if tg_file.file_size:
                    if fmt == "aac":
                        album.aac_zip_size = tg_file.file_size
                    elif fmt == "atmos":
                        album.atmos_zip_size = tg_file.file_size
                    else:
                        album.alac_zip_size = tg_file.file_size
                    session.add(album)
                    await session.commit()

                return web.json_response({
                    "valid": True,
                    "format": fmt,
                    "file_id": file_id,
                    "file_size": tg_file.file_size,
                    "file_path": tg_file.file_path,
                    "message": "File is valid and accessible on Telegram servers.",
                })
        except Exception as e:
            return web.json_response({
                "valid": False,
                "format": fmt,
                "file_id": file_id,
                "error": str(e),
                "message": f"Telegram API error: {str(e)}",
            })
