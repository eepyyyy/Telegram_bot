import datetime
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Optional
from pathlib import Path

from aiohttp import web
from sqlmodel import select, func, or_, col, desc

import bot_control
import database
from database import Tracks, AACTracks, AtmosTracks, Albums, User, async_session
from queues import (
    active_tasks,
    get_queue_stats,
    clear_queue,
    user_locks,
    user_pending_jobs,
    user_in_queue,
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
            else:
                s_term = f"%{search.lstrip('@').lower()}%"
                query = query.where(or_(
                    func.lower(User.username).like(s_term),
                    func.lower(User.first_name).like(s_term)
                ))
        
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
