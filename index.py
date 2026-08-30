import asyncio, glob, os, re, shutil, logging, sys, crud, database, schema, utils
from datetime import date, datetime, timezone

# Ensure stdout/stderr handle UTF-8 symbols safely on Windows
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

from aac import aac, aac_worker
from atmos import atmos, atmos_worker
from lossless import lossless, lossless_worker
from mv import mv, mv_worker, process_mv_enqueue
from artist import test_router

from help import help_router
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import FSInputFile, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.markdown import hbold, hcode, hunderline
from sqlmodel import select
from dotenv import load_dotenv
from database import User, get_session_maker
from gamdlUrl import get_any_url, normalize_apple_music_url
from gamdl.interface import AppleMusicInterface
from queues import (
    download_queue, user_in_queue, user_locks, user_pending_jobs, active_tasks,
    is_user_busy, pending_album_prompts, aac_queue, aac_in_queue, aac_pending_jobs,
    atmos_queue, atmos_in_queue, atmos_pending_jobs
)

import aiohttp
from pathlib import Path
from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
import bot_control
from admin_routes import admin_routes

load_dotenv()


async def wait_for_local_server(local_server_url: str) -> None:
    """
    Waits for the local Telegram Bot API server to respond, using exponential backoff to prevent high CPU spin on startup/idle.
    """
    health_url = f"{local_server_url.rstrip('/')}/"
    delay = 2
    max_delay = 30
    attempts = 0
    logging.info(f"Checking health of local Telegram API server at {local_server_url}...")
    
    async with aiohttp.ClientSession() as session:
        while True:
            attempts += 1
            try:
                async with session.get(health_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    logging.info(f"Local Telegram API server is reachable (HTTP {resp.status})!")
                    return
            except Exception as e:
                logging.warning(
                    f"Local Telegram API server at {local_server_url} is unreachable (attempt {attempts}): {e}. "
                    f"Retrying in {delay}s to avoid CPU spin..."
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)


TOKEN_API = os.getenv("TOKEN_API")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "https://tbot.eepy.in")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "super_secret_webhook_token_123")
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
STREAM_SERVER_URL = os.getenv("STREAM_SERVER_URL", "https://stream.eepy.in")



from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.types import TelegramObject, FSInputFile, Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

LISTEN_HOST = os.getenv("WEBHOOK_LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.getenv("WEBHOOK_LISTEN_PORT", 8080))

dp = Dispatcher()
async_session = get_session_maker()


class MaintenanceMiddleware(BaseMiddleware):
    """
    Blocks incoming user interactions during maintenance mode and replies with a maintenance notice.
    """
    async def __call__(self, handler, event: TelegramObject, data: dict):
        if bot_control.maintenance_mode:
            user_id = None
            if isinstance(event, Message) and event.from_user:
                user_id = event.from_user.id
            elif isinstance(event, CallbackQuery) and event.from_user:
                user_id = event.from_user.id

            admin_id = os.getenv("ADMIN_ID")
            if admin_id and user_id and str(user_id) == str(admin_id):
                return await handler(event, data)

            msg_text = bot_control.maintenance_message or "The bot is currently undergoing maintenance or updates. Please try again shortly."
            if isinstance(event, Message):
                try:
                    await event.answer(f"🚧 <b>Maintenance Mode Active</b>\n\n{msg_text}", parse_mode="HTML")
                except Exception:
                    pass
                return
            elif isinstance(event, CallbackQuery):
                try:
                    await event.answer("🚧 Bot is currently under maintenance. Please try again later.", show_alert=True)
                except Exception:
                    pass
                return

        return await handler(event, data)


dp.message.outer_middleware(MaintenanceMiddleware())
dp.callback_query.outer_middleware(MaintenanceMiddleware())


def make_progress_bar(current: int, total: int, length: int = 10) -> str:
    """
    Renders a dynamic visual progress bar.
    """
    if total <= 0:
        return "[░░░░░░░░░░] 0%"
    percent = min(100, int((current / total) * 100))
    filled = int(length * percent // 100)
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {percent}% ({current}/{total})"


@dp.callback_query(F.data.startswith("cancel_download:"))
async def handle_cancel_download(call: types.CallbackQuery) -> None:
    """
    Handles user cancellation of active download tasks.
    """
    task_id = call.data.split(":")[1]
    if task_id in active_tasks:
        task_info = active_tasks[task_id]
        if task_info["user_id"] != call.from_user.id:
            await call.answer("❌ You can only cancel your own downloads.", show_alert=True)
            return

        task_info["cancelled"] = True
        proc = task_info.get("process")
        if proc and proc.returncode is None:
            try:
                proc.terminate()
            except Exception:
                pass
        await call.answer("🚫 Cancelling download...")
        status_msg = task_info.get("status_msg")
        if status_msg:
            try:
                await status_msg.edit_text("🚫 Download cancelled by user.")
            except Exception:
                pass
    else:
        await call.answer("Task is no longer active.", show_alert=True)


import base64

def decode_deeplink_url(start_param: str) -> str:
    """Decodes Telegram start parameter back into Apple Music URL."""
    if not start_param or not start_param.startswith("dl_"):
        return ""
    raw_b64 = start_param[3:]
    padding = len(raw_b64) % 4
    if padding:
        raw_b64 += "=" * (4 - padding)
    try:
        return base64.urlsafe_b64decode(raw_b64.encode('utf-8')).decode('utf-8')
    except Exception:
        return ""


# Queue management for concurrent downloads

def get_start_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="Web Vault (stream.eepy.in)", url="https://stream.eepy.in/")],
        [InlineKeyboardButton(text="Join Discord Community", url="https://discord.gg/KBy2UMfjx8")],
        [InlineKeyboardButton(text="Apple Music Storefront Search", url="https://am-l.eepy.in/")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(CommandStart())
async def cmd_start(msg: types.Message) -> None:
    """
    Renders the main landing dashboard or processes deep-linked download requests.
    """
    args = (msg.text or "").split(maxsplit=1)
    if len(args) > 1:
        param = args[1].strip()
        target_url = decode_deeplink_url(param)
        if target_url:
            user_id_local = msg.from_user.id
            if is_user_busy(user_id_local):
                await msg.answer("⏳ You already have an active download task in progress. Please wait until it completes.")
                return

            msg = await msg.answer(target_url)

            user_in_queue.add(user_id_local)
            user_pending_jobs[user_id_local] = 1
            position = download_queue.qsize()

            await download_queue.put({
                "url": target_url,
                "msg": msg,
                "user_id": user_id_local,
                "format_type": "alac"
            })
            await msg.answer(f"✅ Queued at position #{position + 1}. Live download progress will update below:")
            return

    welcome_text = (
        f"<b>Apple Music Downloader</b>\n"
        f"Download studio-grade Lossless audio directly from Apple Music.\n\n"
        f"<b>Features</b>\n"
        f"• <b>Audio Quality:</b> ALAC Lossless up to 24-bit / 192kHz\n"
        f"• <b>Artist Support:</b> Send an artist link to fetch top tracks or catalogs\n"
        f"• <b>Limits (cached files do not count):</b>\n"
        f"  ├ ALAC Lossless: 100 downloads per 12 hours\n"
        f"  ├ Music Videos: 50 downloads per day\n"
        f"  └ AAC & Dolby Atmos: Unlimited\n\n"
        f"<b>Note:</b> Artist downloads (<code>/artist</code>) are strictly limited to ALAC format.\n\n"
        f"<b>Note:</b> Regular Lossless downloads (<code>/lossless &lt;url&gt;</code>) are deprecated; please send links directly for normal download.\n\n"
        f"<b>Note:</b> AAC downloads (<code>/aac &lt;url&gt;</code>) AAC 256kbps 44.1kHz.\n\n"
        f"<b>Note:</b> Dolby Atmos downloads (<code>/atmos &lt;url&gt;</code>) Spatial Audio.\n\n"
        f"<b>Note:</b> Music Video downloads (<code>/mv &lt;url&gt;</code>) H.265 / H.264 HD Video.\n\n"

        f"<b>How to Use</b>\n"
        f"Send any track, album, or artist link directly to this chat.\n\n"
        f"<b>Shortcuts & Commands</b>\n"
        f"• Inline search: @applemusicdw_bot\n"
        f"• Web Vault Streaming: https://stream.eepy.in/\n"
        f"• Storefront Search: https://am-l.eepy.in/\n"
        f"• View stats and limits: /info\n"
        f"• View all commands: /help"
    )

    await msg.answer(
        text=welcome_text,
        parse_mode="HTML",
        reply_markup=get_start_keyboard()
    )



@dp.message(lambda msg: bool(msg.text and not msg.text.startswith("/") and re.search(r"https?://", msg.text)))
async def download_handle(msg: types.Message) -> None:
    """
    Handles incoming messages: prompts user with delivery options for full albums,
    or immediately queues single tracks/videos.
    """
    links = re.findall(r"https?://[^\s<>]+", msg.text)
    if not links:
        return

    if len(links) != 1:
        await msg.answer("Please send exactly one Apple Music link.")
        return

    url = links[0]
    if "music-video" in url:
        await process_mv_enqueue(msg, url)
        return

    user_id_local = msg.from_user.id

    if is_user_busy(user_id_local):
        await msg.answer("⏳ You already have a download in progress. Please wait until it's finished.")
        return

    norm_url = normalize_apple_music_url(url)
    try:
        url_info = AppleMusicInterface.get_url_info(norm_url)
    except Exception:
        url_info = None

    # If it's a full album (not an individual track in an album)
    if url_info and url_info.type == "album" and not url_info.sub_id:
        status_msg = await msg.answer("🔍 Fetching album information...")
        try:
            songs = await get_any_url(norm_url)
        except Exception as e:
            try:
                await status_msg.edit_text(f"❌ Failed to fetch album metadata: {str(e)}")
            except Exception:
                pass
            return

        if not songs:
            try:
                await status_msg.edit_text("❌ No tracks found for this album.")
            except Exception:
                pass
            return

        album_id = url_info.id
        album_title = songs[0].album or "Album"
        artist = songs[0].artist or "Unknown Artist"
        track_count = len(songs)

        prompt_key = f"{user_id_local}_{album_id}_alac"
        pending_album_prompts[prompt_key] = {
            "url": norm_url,
            "songs": songs,
            "msg": msg,
            "user_id": user_id_local,
            "format": "alac",
            "album_id": album_id,
            "album_title": album_title,
            "artist": artist
        }

        kb = InlineKeyboardBuilder()
        kb.row(
            types.InlineKeyboardButton(text="🎵 Individual Tracks", callback_data=f"alb_mode:tracks:{prompt_key}"),
            types.InlineKeyboardButton(text="📦 ZIP Archive Only", callback_data=f"alb_mode:zip:{prompt_key}")
        )
        kb.row(
            types.InlineKeyboardButton(text="💿 Tracks + ZIP", callback_data=f"alb_mode:both:{prompt_key}"),
            types.InlineKeyboardButton(text="✖ Cancel", callback_data=f"alb_mode:cancel:{prompt_key}")
        )

        prompt_text = (
            f"💿 <b>Album:</b> {hcode(album_title)}\n"
            f"👤 <b>Artist:</b> {hcode(artist)}\n"
            f"🎵 <b>Tracks:</b> {track_count} track(s)\n"
            f"🎛 <b>Format:</b> Lossless (ALAC)\n\n"
            f"<b>Please choose delivery option:</b>"
        )
        try:
            await status_msg.edit_text(prompt_text, reply_markup=kb.as_markup(), parse_mode="HTML")
        except Exception:
            pass
        return

    # Single track or normal link
    user_in_queue.add(user_id_local)
    user_pending_jobs[user_id_local] = len(links)
    position = download_queue.qsize()
    await msg.answer(f"Queued {len(links)} link(s) (starting at position {position + 1}).")

    for u in links:
        await download_queue.put({
            "url": u,
            "msg": msg,
            "user_id": user_id_local,
            "download_mode": "tracks"
        })


@dp.callback_query(F.data.startswith("alb_mode:"))
async def handle_album_mode_selection(call: types.CallbackQuery) -> None:
    """
    Handles user interaction on the album delivery options prompt.
    """
    parts = call.data.split(":", 2)
    if len(parts) < 3:
        await call.answer("Invalid selection.")
        return

    mode = parts[1]
    prompt_key = parts[2]

    prompt_data = pending_album_prompts.get(prompt_key)
    if not prompt_data:
        await call.answer("⚠️ This album selection has expired. Please send the link again.", show_alert=True)
        try:
            await call.message.delete()
        except Exception:
            pass
        return

    user_id = prompt_data["user_id"]
    if call.from_user.id != user_id:
        await call.answer("❌ You cannot interact with someone else's download request.", show_alert=True)
        return

    if mode == "cancel":
        pending_album_prompts.pop(prompt_key, None)
        try:
            await call.message.edit_text("🚫 Download cancelled by user.")
        except Exception:
            pass
        return

    if is_user_busy(user_id):
        await call.answer("⏳ You already have an active download in progress. Please wait until it completes.", show_alert=True)
        return

    pending_album_prompts.pop(prompt_key, None)
    url = prompt_data["url"]
    songs = prompt_data["songs"]
    orig_msg = prompt_data["msg"]
    fmt = prompt_data.get("format", "alac")
    album_id = prompt_data.get("album_id")
    album_title = prompt_data.get("album_title", "Album")
    artist = prompt_data.get("artist", "Unknown Artist")

    # If ZIP only mode selected, check DB cache first!
    if mode == "zip":
        async with async_session() as session:
            cached_zip_id, cached_gofile_url = await crud.get_cached_album_zip(session, album_id, format_type=fmt)
            if cached_zip_id:
                try:
                    await call.message.edit_text("⚡ Delivering cached album ZIP...")
                    await orig_msg.answer_document(
                        document=cached_zip_id,
                        caption=f"📦 <b>{album_title}</b> ({fmt.upper()})\n👤 <i>{artist}</i>\n⚡ <i>Delivered from cache</i>",
                        parse_mode="HTML"
                    )
                    await call.message.edit_text("✅ Album ZIP delivered from cache!")
                    return
                except Exception as e:
                    print(f"Failed to deliver cached zip document {cached_zip_id}: {e}")
            elif cached_gofile_url:
                try:
                    await call.message.edit_text(
                        f"✅ <b>{album_title}</b> ({fmt.upper()})\n"
                        f"👤 <i>{artist}</i>\n\n"
                        f"⚡ <i>Delivered from cache:</i>\n"
                        f"🌐 <a href='{cached_gofile_url}'><b>Download Album ZIP on GoFile</b></a>",
                        parse_mode="HTML"
                    )
                    return
                except Exception:
                    pass

    # Enqueue to appropriate queue based on fmt
    if fmt == "aac":
        aac_in_queue.add(user_id)
        aac_pending_jobs[user_id] = 1
        pos = aac_queue.qsize()
        try:
            await call.message.edit_text(f"Queued AAC album in {mode.upper()} mode (starting at position {pos + 1})...")
        except Exception:
            pass
        await aac_queue.put({
            "url": url,
            "songs": songs,
            "msg": orig_msg,
            "user_id": user_id,
            "status_msg": call.message,
            "download_mode": mode,
            "album_id": album_id
        })
    elif fmt == "atmos":
        atmos_in_queue.add(user_id)
        atmos_pending_jobs[user_id] = 1
        pos = atmos_queue.qsize()
        try:
            await call.message.edit_text(f"Queued Atmos album in {mode.upper()} mode (starting at position {pos + 1})...")
        except Exception:
            pass
        await atmos_queue.put({
            "url": url,
            "songs": songs,
            "msg": orig_msg,
            "user_id": user_id,
            "status_msg": call.message,
            "download_mode": mode,
            "album_id": album_id
        })
    else:
        user_in_queue.add(user_id)
        user_pending_jobs[user_id] = 1
        pos = download_queue.qsize()
        try:
            await call.message.edit_text(f"Queued ALAC album in {mode.upper()} mode (starting at position {pos + 1})...")
        except Exception:
            pass
        await download_queue.put({
            "url": url,
            "msg": orig_msg,
            "user_id": user_id,
            "status_msg": call.message,
            "download_mode": mode,
            "album_id": album_id,
            "songs": songs
        })


async def process_download(task: dict) -> None:
    """
    Core logic for processing a download request: fetching metadata, checking cache, downloading via gamdl, and uploading to Telegram.
    Supports 'tracks', 'zip', and 'both' delivery modes.
    """
    message = task["url"]  # The specific target album/track URL
    msg: Message = task["msg"]  # The aiogram message context used to reply
    user_id_local = task["user_id"]
    download_mode = task.get("download_mode", "tracks")
    album_id_task = task.get("album_id")

    unique_task_id = f"{msg.message_id}_{int(asyncio.get_event_loop().time() * 1000)}"
    cancel_builder = InlineKeyboardBuilder()
    cancel_builder.row(types.InlineKeyboardButton(text="✖ Cancel Download", callback_data=f"cancel_download:{unique_task_id}"))

    status_msg = task.get("status_msg")
    if not status_msg:
        status_msg = await msg.answer('🔍 Processing request...', reply_markup=cancel_builder.as_markup())
    else:
        try:
            await status_msg.edit_text('🔍 Processing request...', reply_markup=cancel_builder.as_markup())
        except Exception:
            status_msg = await msg.answer('🔍 Processing request...', reply_markup=cancel_builder.as_markup())

    task_output_dir = os.path.join("./downloads", unique_task_id)
    process = None

    import time
    active_tasks[unique_task_id] = {
        "process": None,
        "cancelled": False,
        "user_id": user_id_local,
        "status_msg": status_msg,
        "track_title": "Fetching metadata...",
        "artist": "Unknown Artist",
        "format": "ALAC",
        "status": "fetching",
        "start_time": time.time(),
        "progress": 0,
    }

    try:
        # 1. Fetch metadata from Apple Music if not preloaded
        songs = task.get("songs")
        if not songs:
            try:
                songs = await get_any_url(message)
            except Exception as e:
                try:
                    await status_msg.edit_text(f"❌ Failed to fetch metadata: {str(e)}")
                except Exception:
                    pass
                return

        if songs and unique_task_id in active_tasks:
            if len(songs) == 1:
                active_tasks[unique_task_id]["track_title"] = songs[0].title
                active_tasks[unique_task_id]["artist"] = songs[0].artist
            else:
                active_tasks[unique_task_id]["track_title"] = songs[0].album or f"{songs[0].title} (+{len(songs)-1} tracks)"
                active_tasks[unique_task_id]["artist"] = songs[0].artist
            active_tasks[unique_task_id]["status"] = "downloading"

        total_tracks = len(songs) if songs else 0
        completed_count = 0

        # Check if Lossless (ALAC) is available in Apple Music metadata
        has_lossless = any(
            any(t in (s.audio_traits or []) for t in ("lossless", "hi-res-lossless"))
            for s in songs
        ) if songs else False

        if not has_lossless and songs:
            has_atmos = any(
                any(t in (s.audio_traits or []) for t in ("atmos", "spatial"))
                for s in songs
            )
            if has_atmos:
                suggestion = (
                    "⚠️ <b>Lossless (ALAC) is not available</b> for this item on Apple Music.\n\n"
                    "Available formats:\n"
                    "• Use <code>/aac &lt;link&gt;</code> for AAC 256kbps\n"
                    "• Use <code>/atmos &lt;link&gt;</code> for Dolby Atmos"
                )
            else:
                suggestion = (
                    "⚠️ <b>Lossless (ALAC) is not available</b> for this item on Apple Music.\n\n"
                    "👉 Please use <code>/aac &lt;link&gt;</code> to download in AAC 256kbps format."
                )
            try:
                await status_msg.edit_text(suggestion, parse_mode="HTML")
            except Exception:
                pass
            return

        # Check ZIP Cache if download_mode is 'zip'
        album_id = album_id_task or (songs[0].album_id if songs else None)
        if download_mode == "zip" and album_id:
            async with async_session() as session:
                cached_zip_fid, cached_gofile_url = await crud.get_cached_album_zip(session, album_id, format_type="alac")
                if cached_zip_fid:
                    try:
                        await msg.answer_document(
                            document=cached_zip_fid,
                            caption=f"📦 <b>{songs[0].album}</b> (Lossless ALAC)\n👤 <i>{songs[0].artist}</i>\n⚡ <i>Delivered from cache</i>",
                            parse_mode="HTML"
                        )
                        await status_msg.edit_text("✅ Album ZIP delivered from cache!")
                        return
                    except Exception as e:
                        print(f"Failed to deliver cached ALAC zip document: {e}")
                elif cached_gofile_url:
                    await msg.answer(
                        f"📦 <b>{songs[0].album}</b> (Lossless ALAC)\n"
                        f"👤 <i>{songs[0].artist}</i>\n\n"
                        f"⚡ <i>Delivered from cache:</i>\n"
                        f"🌐 <a href='{cached_gofile_url}'><b>Download Album ZIP on GoFile</b></a>",
                        parse_mode="HTML"
                    )
                    await status_msg.edit_text("✅ Cached Album ZIP link delivered!")
                    return

        # 2. Check database for existing file_ids (for tracks/both modes)
        file_ids, tracks_to_download = await crud.check_db_for_urls(songs)

        async with async_session() as session:
            # 3. Get or create user and check limits
            statement = select(User).where(User.user_id == user_id_local)
            result = await session.exec(statement)
            user = result.first()

            if not user:
                user = User(user_id=user_id_local)
                session.add(user)
                await session.commit()
                await session.refresh(user)

            current_date = datetime.now(timezone.utc).date()
            if not user.is_premium:
                if user.last_download != current_date:
                    user.downloaded_today = 0
                    user.last_download = current_date
                    session.add(user)
                    await session.commit()

            # 4. Deliver cached tracks (if tracks or both mode)
            if download_mode in ("tracks", "both"):
                for file_id in file_ids:
                    if active_tasks.get(unique_task_id, {}).get("cancelled"):
                        try:
                            await status_msg.edit_text("🚫 Download cancelled by user.")
                        except Exception:
                            pass
                        return

                    try:
                        sent_msg = await msg.answer_audio(audio=file_id)
                    except Exception:
                        sent_msg = None

                    if sent_msg:
                        completed_count += 1
                        user.download_count += 1
                        session.add(user)
                        await session.commit()

                        # Log cached delivery
                        try:
                            db_track = (await session.exec(select(database.Tracks).where(database.Tracks.file_id == file_id))).first()
                            song_id_val = db_track.song_id if db_track else None
                            size_val = db_track.size if db_track else 0
                            await crud.log_download(
                                session=session,
                                user_id=user_id_local,
                                song_id=song_id_val,
                                format_type="alac",
                                size=size_val,
                                is_cached=True
                            )
                            await session.commit()
                        except Exception as le:
                            print(f"Failed to log cached download history: {le}")

                        # Real-Time Progress Bar Update
                        progress_text = (
                            f"🚀 {hbold('DELIVERING FROM CACHE')}\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"{make_progress_bar(completed_count, total_tracks)}\n"
                            f"⚡ Delivered {completed_count}/{total_tracks} track(s)"
                        )
                        try:
                            await status_msg.edit_text(progress_text, reply_markup=cancel_builder.as_markup())
                        except Exception:
                            pass

            if not user.is_premium:
                alac_count = await crud.get_alac_download_count_12h(session, user_id_local)
                if alac_count >= 100:
                    try:
                        await status_msg.edit_text("❌ ALAC download limit reached (100 tracks per 12 hours).")
                    except Exception:
                        pass
                    return

            if download_mode == "tracks" and not tracks_to_download:
                try:
                    await status_msg.edit_text("✅ All tracks delivered from cache!\n\n🌐 Link can be downloaded at: https://stream.eepy.in/")
                except Exception:
                    pass
                return

        # 5. Download tracks using gamdl
        # For ZIP mode, download all tracks of the album even if some are in DB, so the archive is 100% complete
        target_dl_urls = tracks_to_download if download_mode == "tracks" else [s.url for s in songs]

        progress_text = (
            f"🚀 {hbold('DOWNLOADING ALBUM' if download_mode in ('zip', 'both') else 'DOWNLOADING TRACKS')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{make_progress_bar(completed_count, total_tracks)}\n"
            f"📥 Downloading {len(target_dl_urls)} track(s)..."
        )
        try:
            await status_msg.edit_text(progress_text, reply_markup=cancel_builder.as_markup())
        except Exception:
            pass

        task_temp_dir = f"{task_output_dir}_temp"
        await asyncio.to_thread(os.makedirs, task_output_dir, exist_ok=True)
        await asyncio.to_thread(os.makedirs, task_temp_dir, exist_ok=True)
        
        cookies_path = os.path.abspath("cookies.txt")
        cookies_args = ["--cookies-path", cookies_path] if os.path.exists(cookies_path) else []
        
        # Save max-res cover as separate file
        cover_args = ["--save-cover", "--cover-format", "jpg", "--cover-size", "5000"]

        process = await asyncio.create_subprocess_exec(
            "gamdl",
            *cookies_args,
            *cover_args,
            "--truncate", "80",
            "--output-path", task_output_dir,
            "--temp-path", task_temp_dir,
            *target_dl_urls,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            limit=10 * 1024 * 1024,
        )
        if unique_task_id in active_tasks:
            active_tasks[unique_task_id]["process"] = process

        ansi_escapes = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        already_processed = set()

        while True:
            if active_tasks.get(unique_task_id, {}).get("cancelled"):
                try:
                    process.terminate()
                    await process.wait()
                except ProcessLookupError:
                    pass
                return

            try:
                line_bytes = await process.stdout.readline()
            except (ValueError, asyncio.LimitOverrunError):
                try:
                    line_bytes = await process.stdout.read(8192)
                except Exception:
                    line_bytes = b""
            except Exception:
                line_bytes = b""

            if not line_bytes:
                break
            
            line = ansi_escapes.sub("", line_bytes.decode("utf-8", errors="ignore")).strip()
            if line:
                print(f"[gamdl] {line}")
                if "Requested format is not available" in line:
                    try:
                        process.terminate()
                        await process.wait()
                    except ProcessLookupError:
                        pass
                    try:
                        await status_msg.edit_text(
                            "⚠️ <b>Requested format (Lossless ALAC) is not available</b> for this track/album.\n\n"
                            "👉 Please use <code>/aac &lt;link&gt;</code> to download in AAC 256kbps format.",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
                    return

            # Check for finalized .m4a files in output directory
            downloaded_files = await asyncio.to_thread(
                glob.glob, f"{task_output_dir}/**/*.m4a", recursive=True
            )
            for file_path in downloaded_files:
                norm_p = file_path.replace("\\", "/")
                filename = os.path.basename(norm_p)
                if "gamdl_temp" in norm_p or "_temp" in norm_p or filename.endswith("_encrypted.m4a") or filename.endswith(".tmp"):
                    continue

                if active_tasks.get(unique_task_id, {}).get("cancelled"):
                    try:
                        process.terminate()
                        await process.wait()
                    except ProcessLookupError:
                        pass
                    return

                if file_path not in already_processed:
                    already_processed.add(file_path)
                    
                    if download_mode == "zip":
                        # In ZIP-only mode, don't send individual audio tracks to PM; just update progress
                        completed_count += 1
                        progress_text = (
                            f"🚀 {hbold('PACKAGING ALBUM')}\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"{make_progress_bar(completed_count, total_tracks)}\n"
                            f"📥 Downloaded {completed_count}/{total_tracks} tracks..."
                        )
                        try:
                            await status_msg.edit_text(progress_text, reply_markup=cancel_builder.as_markup())
                        except Exception:
                            pass
                        continue

                    # For 'tracks' or 'both' mode, deliver audio track
                    async with async_session() as session:
                        result = await session.exec(select(User).where(User.user_id == user_id_local))
                        user = result.one()
                        
                        if not user.is_premium:
                            alac_count = await crud.get_alac_download_count_12h(session, user_id_local)
                            if alac_count >= 100:
                                try:
                                    await msg.answer("❌ ALAC download limit reached (100 tracks per 12 hours). Stopping further downloads.")
                                except Exception:
                                    pass
                                try:
                                    process.terminate()
                                    await process.wait()
                                except ProcessLookupError:
                                    pass
                                return

                        # Extract metadata and upload
                        track_title, artist, thumbnail, duration, isrc = await asyncio.to_thread(
                            utils.extract_track_metadata, file_path
                        )
                        
                        sent_msg, saved_chat_id, saved_message_id = await utils.upload_and_deliver_audio(
                            bot=msg.bot,
                            user_chat_id=msg.chat.id,
                            file_path=file_path,
                            title=track_title,
                            performer=artist,
                            thumbnail=thumbnail,
                            duration=duration
                        )

                        if sent_msg:
                            completed_count += 1
                            user.download_count += 1
                            session.add(user)
                            await session.commit()

                            # Real-Time Progress Bar Update
                            progress_text = (
                                f"🚀 {hbold('PROCESSING DOWNLOAD')}\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"{make_progress_bar(completed_count, total_tracks)}\n"
                                f"🎵 {hbold('Uploaded:')} {hcode(track_title)}"
                            )
                            try:
                                await status_msg.edit_text(progress_text, reply_markup=cancel_builder.as_markup())
                            except Exception:
                                pass

                            media_obj = sent_msg.audio or sent_msg.document
                            file_id_val = media_obj.file_id if media_obj else None
                            file_uniq_val = media_obj.file_unique_id if media_obj else None
                            file_sz_val = getattr(media_obj, "file_size", 0) if media_obj else 0

                            tbot = schema.TrackInputSchema(
                                file_id=file_id_val,
                                file_unique_id=file_uniq_val,
                                title=track_title,
                                size=file_sz_val,
                                isrc=isrc,
                                chat_id=saved_chat_id,
                                message_id=saved_message_id
                            )
                            
                            matched = False
                            # 1. Match by ISRC
                            if isrc:
                                for original_track in songs:
                                    if original_track.isrc == isrc:
                                        track_input = schema.TrackInputSchema(**original_track.model_dump())
                                        track_input.file_id = tbot.file_id
                                        track_input.file_unique_id = tbot.file_unique_id
                                        track_input.size = tbot.size
                                        track_input.chat_id = tbot.chat_id
                                        track_input.message_id = tbot.message_id
                                        await crud.save_single_track(session=session, track_data=track_input)
                                        await session.commit()
                                        
                                        try:
                                            await crud.log_download(
                                                session=session,
                                                user_id=user_id_local,
                                                song_id=track_input.song_id,
                                                format_type="alac",
                                                size=tbot.size,
                                                is_cached=False
                                            )
                                            await session.commit()
                                        except Exception as le:
                                            print(f"Failed to log download history: {le}")
                                            
                                        matched = True
                                        break

                            # 2. Fallback to normalized title match
                            if not matched:
                                for original_track in songs:
                                    if utils.convert_text(original_track.title) == utils.convert_text(tbot.title):
                                        track_input = schema.TrackInputSchema(**original_track.model_dump())
                                        track_input.file_id = tbot.file_id
                                        track_input.file_unique_id = tbot.file_unique_id
                                        track_input.size = tbot.size
                                        track_input.chat_id = tbot.chat_id
                                        track_input.message_id = tbot.message_id
                                        await crud.save_single_track(session=session, track_data=track_input)
                                        await session.commit()
                                        
                                        try:
                                            await crud.log_download(
                                                session=session,
                                                user_id=user_id_local,
                                                song_id=track_input.song_id,
                                                format_type="alac",
                                                size=tbot.size,
                                                is_cached=False
                                            )
                                            await session.commit()
                                        except Exception as le:
                                            print(f"Failed to log download history: {le}")
                                            
                                        break

                        # In 'tracks' mode only, delete local file immediately after upload
                        if download_mode == "tracks":
                            try:
                                await asyncio.to_thread(os.remove, file_path)
                            except Exception as e:
                                print(f"Failed to delete {file_path}: {e}")

            await asyncio.sleep(1)

        return_code = await process.wait()

        # Handle ZIP Generation & Delivery for 'zip' and 'both' modes
        if not active_tasks.get(unique_task_id, {}).get("cancelled") and download_mode in ("zip", "both"):
            try:
                await status_msg.edit_text("📦 Packaging album into ZIP with max-res cover and lyrics (.lrc, .srt, .ttml)...")
            except Exception:
                pass

            # Save cover art and all lyric formats into folder
            await utils.save_album_cover_and_lyrics(songs, task_output_dir)

            # Build ZIP archive
            album_title = songs[0].album or "Album"
            artist = songs[0].artist or "Unknown Artist"
            clean_album = re.sub(r'[\\/*?:"<>|]', "", album_title)
            clean_artist = re.sub(r'[\\/*?:"<>|]', "", artist)
            zip_filename = f"{clean_artist} - {clean_album} [Lossless ALAC].zip"
            zip_path = os.path.join(os.path.dirname(task_output_dir), zip_filename)

            await utils.create_album_zip(task_output_dir, zip_path)

            caption = (
                f"📦 <b>{album_title}</b> (Lossless ALAC)\n"
                f"👤 <i>{artist}</i>\n"
                f"🎵 {len(songs)} Tracks • Max-Res Cover • All Lyrics (.lrc, .srt, .ttml)"
            )

            thumb_data = None
            cover_file = os.path.join(task_output_dir, "Cover.jpg")
            if os.path.exists(cover_file):
                try:
                    with open(cover_file, "rb") as cf:
                        thumb_data = types.BufferedInputFile(cf.read(), filename="thumb.jpg")
                except Exception:
                    pass

            try:
                await status_msg.edit_text("🚀 Uploading Album ZIP to Telegram...")
            except Exception:
                pass

            sent_doc, saved_cid, saved_mid, zip_fid, gofile_url = await utils.upload_and_deliver_zip_document(
                bot=msg.bot,
                user_chat_id=msg.chat.id,
                file_path=zip_path,
                caption=caption,
                thumbnail=thumb_data
            )

            # Save cached ZIP file_id and/or gofile_url
            if album_id:
                async with async_session() as session:
                    await crud.save_cached_album_zip(
                        session=session,
                        album_id=album_id,
                        album_name=album_title,
                        artist=artist,
                        format_type="alac",
                        zip_file_id=zip_fid,
                        gofile_url=gofile_url
                    )

            if gofile_url and not zip_fid:
                await msg.answer(
                    f"📦 <b>{album_title}</b> (Lossless ALAC)\n"
                    f"👤 <i>{artist}</i>\n\n"
                    f"⚡ <i>File size exceeds 2GB Telegram limit. Uploaded to GoFile:</i>\n"
                    f"🌐 <a href='{gofile_url}'><b>Download Album ZIP on GoFile</b></a>",
                    parse_mode="HTML"
                )

            if os.path.exists(zip_path):
                try:
                    os.remove(zip_path)
                except Exception:
                    pass

            try:
                await status_msg.edit_text("✅ Album download and packaging completed successfully!\n\n🌐 Link can also be downloaded at: https://stream.eepy.in/")
            except Exception:
                pass
            return

        if not active_tasks.get(unique_task_id, {}).get("cancelled"):
            if return_code == 0:
                try:
                    await status_msg.edit_text("✅ All tracks processed successfully.\n\n🌐 Link can be downloaded at: https://stream.eepy.in/")
                except Exception:
                    pass
            else:
                try:
                    await status_msg.edit_text("⚠ Some tracks might have failed to download.\n\n🌐 Link can be downloaded at: https://stream.eepy.in/")
                except Exception:
                    pass

    except Exception as e:
        print(f"Error handling download: {e}")
        try:
            await msg.answer(f"⚠️ An unexpected error occurred. {str(e)}")
        except Exception:
            pass
    finally:
        active_tasks.pop(unique_task_id, None)
        if process and process.returncode is None:
            try:
                process.terminate()
                await process.wait()
            except ProcessLookupError:
                pass
        for dir_to_clean in (task_output_dir, f"{task_output_dir}_temp"):
            if await asyncio.to_thread(os.path.exists, dir_to_clean):
                try:
                    await asyncio.to_thread(shutil.rmtree, dir_to_clean)
                except Exception as e:
                    print(f"Failed to delete {dir_to_clean}: {e}")



async def worker() -> None:
    """
    Worker function to process the download queue.
    """
    while True:
        while bot_control.is_bot_paused:
            await asyncio.sleep(1)

        task = await download_queue.get()
        msg = task.get("msg") or task.get("message")
        user_id = task.get("user_id")
        if not user_id and msg and hasattr(msg, "from_user") and msg.from_user:
            user_id = msg.from_user.id

        if not user_id or not msg:
            print(f"Worker received malformed task: {task}")
            download_queue.task_done()
            continue

        user_lock = user_locks.setdefault(user_id, asyncio.Lock())

        async with user_lock:
            try:
                # Check database limit before starting download subprocess
                async with async_session() as session:
                    result = await session.exec(select(User).where(User.user_id == user_id))
                    user = result.first()
                    if user:
                        if not user.is_premium:
                            alac_count = await crud.get_alac_download_count_12h(session, user_id)
                            if alac_count >= 100:
                                try:
                                    await msg.answer("❌ ALAC download limit reached (100 tracks per 12 hours). Skipping queued item.")
                                except Exception:
                                    pass
                                continue

                await process_download(task)
            except Exception as e:
                print(f"Worker caught execution exception for user {user_id}: {e}")
            finally:
                remaining = user_pending_jobs.get(user_id, 1) - 1
                if remaining <= 0:
                    user_pending_jobs.pop(user_id, None)
                    user_in_queue.discard(user_id)
                    user_locks.pop(user_id, None)
                else:
                    user_pending_jobs[user_id] = remaining
                download_queue.task_done()

async def on_startup(bot: Bot) -> None:
    """
    Startup handler: initializes database, background workers, and sets the webhook with health checks.
    """
    local_server_url = os.getenv("LOCAL_SERVER_URL", "http://127.0.0.1:8081")
    await wait_for_local_server(local_server_url)

    await database.init_db()

    # Start configurable concurrent workers (default 1 concurrent)
    worker_count = int(os.getenv("WORKER_CONCURRENCY", "3"))
    lossless_worker_count = int(os.getenv("LOSSLESS_WORKER_CONCURRENCY", "3"))
    aac_worker_count = int(os.getenv("AAC_WORKER_CONCURRENCY", "4"))
    atmos_worker_count = int(os.getenv("ATMOS_WORKER_CONCURRENCY", "4"))
    mv_worker_count = int(os.getenv("MV_WORKER_CONCURRENCY", "1"))

    for _ in range(worker_count):
        asyncio.create_task(worker())

    for _ in range(lossless_worker_count):
        asyncio.create_task(lossless_worker())

    for _ in range(aac_worker_count):
        asyncio.create_task(aac_worker())

    for _ in range(atmos_worker_count):
        asyncio.create_task(atmos_worker())

    for _ in range(mv_worker_count):
        asyncio.create_task(mv_worker())

    # Set webhook on local Telegram API server with backoff retries
    webhook_set = False
    delay = 2
    max_delay = 30
    while not webhook_set:
        try:
            logging.info(f"Setting webhook to: {WEBHOOK_URL}")
            await bot.set_webhook(
                url=WEBHOOK_URL,
                secret_token=WEBHOOK_SECRET,
                drop_pending_updates=True,
            )
            webhook_set = True
            logging.info("Webhook successfully configured.")
        except Exception as e:
            logging.error(f"Failed to set webhook: {e}. Retrying in {delay}s...")
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)


    # Register bot commands menu
    try:
        await bot.set_my_commands([
            types.BotCommand(command="start", description="Start the bot & landing dashboard"),
            types.BotCommand(command="lossless", description="Download in regular Lossless (up to 48kHz)"),
            types.BotCommand(command="artist", description="Download artist top tracks or catalog"),
            types.BotCommand(command="aac", description="Download track/album in AAC 256kbps"),
            types.BotCommand(command="atmos", description="Download track/album in Dolby Atmos"),
            types.BotCommand(command="mv", description="Download Music Video in H.265/H.264"),
            types.BotCommand(command="info", description="View download statistics and limits"),
            types.BotCommand(command="help", description="View help and usage instructions"),
        ])
        logging.info("Bot commands successfully registered.")
    except Exception as e:
        logging.warning(f"Failed to set bot commands: {e}")


async def on_shutdown(bot: Bot) -> None:
    """
    Shutdown handler: removes the webhook when the server stops.
    """
    logging.info("Deleting webhook...")
    await bot.delete_webhook()
    logging.info("Webhook successfully deleted.")


def main() -> None:
    """
    Main entry point for the bot using Webhooks with forced Local Telegram API server.
    """
    local_server_url = os.getenv("LOCAL_SERVER_URL", "http://127.0.0.1:8081")
    if not local_server_url:
        raise ValueError("LOCAL_SERVER_URL environment variable must be set to use local Telegram API server.")

    logging.info(f"Enforcing local Telegram API server: {local_server_url}")
    local_server = TelegramAPIServer.from_base(local_server_url)
    session = AiohttpSession(api=local_server, timeout=300)

    bot = Bot(
        token=TOKEN_API,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    dp.include_router(test_router)
    dp.include_router(lossless)
    dp.include_router(aac)
    dp.include_router(atmos)
    dp.include_router(mv)
    dp.include_router(help_router)


    # Register lifecycle hooks
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Create aiohttp web application
    app = web.Application()

    # Create request handler for aiogram updates
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET,
    )

    # Register webhook handler on path
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)

    # Bind app & dispatcher together
    setup_application(app, dp, bot=bot)

    # Register admin REST API routes
    app.add_routes(admin_routes)

    # Serve static dashboard if built
    dashboard_dist = Path(__file__).resolve().parent / "dashboard" / "dist"
    if dashboard_dist.exists():
        # Support both /dashboard/assets and /assets paths
        app.router.add_static("/dashboard/assets", dashboard_dist / "assets", name="dashboard_assets")
        app.router.add_static("/assets", dashboard_dist / "assets", name="root_assets")
        
        async def redirect_dashboard_slash(request: web.Request):
            return web.HTTPFound("/dashboard/")

        async def serve_dashboard_root(request: web.Request):
            return web.FileResponse(dashboard_dist / "index.html")

        # Redirect /dashboard -> /dashboard/ for proper relative asset resolution
        app.router.add_get("/dashboard", redirect_dashboard_slash)
        app.router.add_get("/dashboard/", serve_dashboard_root)

        async def serve_dashboard_sub(request: web.Request):
            tail = request.match_info.get("tail", "")
            req_path = dashboard_dist / tail
            if req_path.is_file():
                return web.FileResponse(req_path)
            return web.FileResponse(dashboard_dist / "index.html")

        app.router.add_get("/dashboard/{tail:.*}", serve_dashboard_sub)

    logging.info(f"Starting webhook web server on {LISTEN_HOST}:{LISTEN_PORT}...")
    web.run_app(app, host=LISTEN_HOST, port=LISTEN_PORT, access_log=None)


def setup_bot_logging():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    # 1. Root logger configuration
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Silence noisy HTTP access logs from polling dashboard endpoints
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.server").setLevel(logging.WARNING)

    # Clean up existing handlers if re-running in interactive environments
    if logger.hasHandlers():
        logger.handlers.clear()

    # 2. Format: includes timestamp, log level, module name, and message
    formatter = logging.Formatter(
        "%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 3. Terminal Handler (Live streaming to console only)
    raw_stdout = sys.stdout
    console_handler = logging.StreamHandler(raw_stdout)
    console_handler.setFormatter(formatter)

    # 4. Attach console handler and in-memory dashboard log handler
    logger.addHandler(console_handler)
    logger.addHandler(bot_control.dashboard_log_handler)

    # 5. Redirect stdout prints (e.g. gamdl output) to logger
    sys.stdout = bot_control.LogRedirectStream(raw_stdout, logger_name="bot.downloader")


if __name__ == "__main__":
    setup_bot_logging()
    main()