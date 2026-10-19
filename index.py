import asyncio, glob, os, re, shutil, logging, sys, html, crud, database, schema, utils
import audio_service
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
import converters
import gamdlHelpUrl

from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import (
    FSInputFile, Message, InlineKeyboardMarkup, InlineKeyboardButton,
    InlineQuery, InlineQueryResultAudio, InlineQueryResultArticle, InputTextMessageContent
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.markdown import hbold, hcode, hunderline
from sqlmodel import select, or_, desc
from dotenv import load_dotenv
from database import User, Tracks, AACTracks, AtmosTracks, get_session_maker
from gamdlUrl import get_any_url, normalize_apple_music_url
from gamdl.interface import AppleMusicInterface
from queues import (
    download_queue, user_in_queue, user_locks, user_pending_jobs, active_tasks,
    is_user_busy, pending_album_prompts, aac_queue, aac_in_queue, aac_pending_jobs,
    atmos_queue, atmos_in_queue, atmos_pending_jobs, cancel_user_queue,
    get_user_queue_status, cancel_user_active_downloads, clear_user_pending_queue
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
            allowed_ids = {"6328734431"}
            if admin_id:
                for a_id in str(admin_id).split(","):
                    if a_id.strip():
                        allowed_ids.add(a_id.strip())

            if user_id and str(user_id) in allowed_ids:
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
        async_task = task_info.get("async_task")
        if async_task and hasattr(async_task, "cancel") and not async_task.done():
            try:
                async_task.cancel()
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


@dp.message(Command("cancel", "quit", "clear"))
async def handle_user_cancel_command(msg: types.Message) -> None:
    """Checks active and queued downloads for the user and asks what they want to cancel."""
    user_id = msg.from_user.id if msg.from_user else msg.chat.id
    status = get_user_queue_status(user_id)
    active_count = status["active_count"]
    queued_count = status["queued_count"]

    if active_count == 0 and queued_count == 0:
        await msg.answer(
            "ℹ️ You don't have any active downloads or queued items right now.",
            parse_mode="HTML"
        )
        return

    kb = InlineKeyboardBuilder()
    if active_count > 0:
        kb.row(InlineKeyboardButton(text=f"🛑 Stop Active Download ({active_count})", callback_data=f"cancel_act:active:{user_id}"))
    if queued_count > 0:
        kb.row(InlineKeyboardButton(text=f"🗑️ Clear Pending Queue ({queued_count})", callback_data=f"cancel_act:queue:{user_id}"))
    if active_count > 0 and queued_count > 0:
        kb.row(InlineKeyboardButton(text="💥 Cancel Everything & Reset", callback_data=f"cancel_act:all:{user_id}"))
    kb.row(InlineKeyboardButton(text="❌ Dismiss / Keep Downloading", callback_data=f"cancel_act:dismiss:{user_id}"))

    await msg.answer(
        f"⚙️ <b>Queue & Download Management</b>\n\n"
        f"• <b>Active Downloading:</b> <code>{active_count}</code> item(s)\n"
        f"• <b>Waiting in Queue:</b> <code>{queued_count}</code> item(s)\n\n"
        f"<i>Please select what you would like to cancel:</i>",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("cancel_act:"))
async def handle_cancel_act_callback(call: types.CallbackQuery) -> None:
    """Handles specific cancellation actions (active only, queue only, or everything)."""
    parts = call.data.split(":")
    if len(parts) < 3:
        return
    action = parts[1]
    try:
        target_user_id = int(parts[2])
    except Exception:
        target_user_id = call.from_user.id

    if call.from_user.id != target_user_id:
        await call.answer("❌ This menu is not for you.", show_alert=True)
        return

    if action == "dismiss":
        await call.answer("Dismissed.")
        try:
            await call.message.delete()
        except Exception:
            pass
        return

    if action == "active":
        cancelled = cancel_user_active_downloads(target_user_id)
        await call.answer(f"🛑 Cancelled {cancelled} active download(s).")
        try:
            await call.message.edit_text(
                f"🛑 <b>Active Download Cancelled!</b>\n\n"
                f"• Stopped <code>{cancelled}</code> active downloading item(s).\n"
                f"• Pending items in your queue will continue automatically.",
                parse_mode="HTML"
            )
        except Exception:
            pass
        return

    if action == "queue":
        cleared = clear_user_pending_queue(target_user_id)
        await call.answer(f"🗑️ Cleared {cleared} queued item(s).")
        try:
            await call.message.edit_text(
                f"🗑️ <b>Queue Cleared!</b>\n\n"
                f"• Removed <code>{cleared}</code> pending item(s) from the queue.\n"
                f"• Your currently active download will finish uninterrupted.",
                parse_mode="HTML"
            )
        except Exception:
            pass
        return

    if action == "all":
        res = cancel_user_queue(target_user_id)
        await call.answer("💥 Everything cancelled & reset.")
        try:
            await call.message.edit_text(
                f"💥 <b>Everything Cancelled & Reset!</b>\n\n"
                f"• Active downloads stopped: <code>{res['active_cancelled']}</code>\n"
                f"• Queued items removed: <code>{res['queued_removed']}</code>\n\n"
                f"✨ You can now start fresh!",
                parse_mode="HTML"
            )
        except Exception:
            pass
        return


@dp.callback_query(F.data.startswith("manage_cancel:") | F.data.startswith("quit_queue:"))
async def handle_manage_cancel_callback(call: types.CallbackQuery) -> None:
    """Opens interactive cancellation menu when clicking cancel button on queue messages."""
    try:
        user_id_str = call.data.split(":", 1)[1]
        target_user_id = int(user_id_str)
    except Exception:
        target_user_id = call.from_user.id

    if call.from_user.id != target_user_id:
        await call.answer("❌ This menu is not for you.", show_alert=True)
        return

    status = get_user_queue_status(target_user_id)
    active_count = status["active_count"]
    queued_count = status["queued_count"]

    if active_count == 0 and queued_count == 0:
        await call.answer("ℹ️ No active or queued downloads right now.", show_alert=True)
        try:
            await call.message.edit_text("ℹ️ You don't have any active downloads or queued items right now.")
        except Exception:
            pass
        return

    kb = InlineKeyboardBuilder()
    if active_count > 0:
        kb.row(InlineKeyboardButton(text=f"🛑 Stop Active Download ({active_count})", callback_data=f"cancel_act:active:{target_user_id}"))
    if queued_count > 0:
        kb.row(InlineKeyboardButton(text=f"🗑️ Clear Pending Queue ({queued_count})", callback_data=f"cancel_act:queue:{target_user_id}"))
    if active_count > 0 and queued_count > 0:
        kb.row(InlineKeyboardButton(text="💥 Cancel Everything & Reset", callback_data=f"cancel_act:all:{target_user_id}"))
    kb.row(InlineKeyboardButton(text="❌ Dismiss / Keep Downloading", callback_data=f"cancel_act:dismiss:{target_user_id}"))

    await call.answer()
    try:
        await call.message.answer(
            f"⚙️ <b>Queue & Download Management</b>\n\n"
            f"• <b>Active Downloading:</b> <code>{active_count}</code> item(s)\n"
            f"• <b>Waiting in Queue:</b> <code>{queued_count}</code> item(s)\n\n"
            f"<i>Please select what you would like to cancel:</i>",
            reply_markup=kb.as_markup(),
            parse_mode="HTML"
        )
    except Exception:
        pass


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


def encode_deeplink_url(url: str) -> str:
    """Encodes Apple Music URL into Telegram start parameter (dl_base64)."""
    if not url:
        return ""
    b64 = base64.urlsafe_b64encode(url.encode('utf-8')).decode('utf-8').rstrip('=')
    return f"dl_{b64}"


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
            quit_kb = types.InlineKeyboardMarkup(inline_keyboard=[
                [types.InlineKeyboardButton(text="🛑 Cancel / Manage Queue", callback_data=f"manage_cancel:{user_id_local}")]
            ])
            await msg.answer(
                f"✅ Queued at position #{position + 1}. Live download progress will update below:",
                reply_markup=quit_kb
            )
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
    Handles incoming messages: resolves Spotify/YouTube/Tidal links to Apple Music,
    prompts user with delivery options for full albums, or queues single tracks.
    """
    links = re.findall(r"https?://[^\s<>]+", msg.text)
    if not links:
        return

    if len(links) != 1:
        await msg.answer("Please send exactly one media link.")
        return

    url = links[0]

    # 1. Cross-Platform Link Resolver (Spotify / YouTube / Tidal -> Apple Music)
    cross_info = converters.is_cross_platform_url(url)
    if cross_info:
        platform, m_type = cross_info
        status_msg = await msg.answer(
            f"🔄 <b>Resolving {platform.capitalize()} link...</b>\n"
            f"Searching Apple Music for high-resolution lossless match...",
            parse_mode="HTML"
        )
        resolved_url, meta = await converters.resolve_cross_platform_link(url)
        if not resolved_url:
            try:
                await status_msg.edit_text(
                    f"❌ Could not find an exact Apple Music match for this {platform.capitalize()} link.\n"
                    f"<i>Tip: Try sending the Apple Music link directly or searching via inline query.</i>",
                    parse_mode="HTML"
                )
            except Exception:
                pass
            return

        matched_title = (meta or {}).get("matched_title") or (meta or {}).get("title") or "Track"
        matched_artist = (meta or {}).get("matched_artist") or (meta or {}).get("artist") or "Artist"
        try:
            await status_msg.edit_text(
                f"✨ <b>Matched on Apple Music:</b>\n"
                f"🎵 <b>{html.escape(matched_title)}</b> — {html.escape(matched_artist)}\n"
                f"⚡ Processing download...",
                parse_mode="HTML"
            )
        except Exception:
            pass
        url = resolved_url
        links = [resolved_url]

    if "music-video" in url:
        await process_mv_enqueue(msg, url)
        return

    user_id_local = msg.from_user.id

    if is_user_busy(user_id_local):
        await msg.answer("⏳ You already have a download in progress. Please wait until it's finished.")
        return

    # Check user preferred format
    user_pref_fmt = "alac"
    try:
        async with async_session() as session:
            user_pref_fmt = await crud.get_user_preferred_format(session, user_id_local)
    except Exception:
        pass

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

        prompt_key = f"{user_id_local}_{album_id}_{user_pref_fmt}"
        pending_album_prompts[prompt_key] = {
            "url": norm_url,
            "songs": songs,
            "msg": msg,
            "user_id": user_id_local,
            "format": user_pref_fmt,
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

        fmt_display = {
            "alac": "Lossless (ALAC)",
            "flac": "Uncompressed FLAC",
            "mp3": "MP3 320kbps",
            "aac": "AAC 256kbps",
            "atmos": "Dolby Atmos"
        }.get(user_pref_fmt, user_pref_fmt.upper())

        prompt_text = (
            f"💿 <b>Album:</b> {hcode(album_title)}\n"
            f"👤 <b>Artist:</b> {hcode(artist)}\n"
            f"🎵 <b>Tracks:</b> {track_count} track(s)\n"
            f"🎛 <b>Format:</b> {fmt_display}\n\n"
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
    quit_kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🛑 Cancel / Manage Queue", callback_data=f"manage_cancel:{user_id_local}")]
    ])
    await msg.answer(f"Queued {len(links)} link(s) (starting at position {position + 1}).", reply_markup=quit_kb)

    for u in links:
        await download_queue.put({
            "url": u,
            "msg": msg,
            "user_id": user_id_local,
            "download_mode": "tracks",
            "format_type": user_pref_fmt
        })


@dp.message(Command("flac"))
async def flac_download_command(msg: types.Message, command: CommandObject) -> None:
    """
    Handles /flac command: downloads ALAC master and transcodes on-the-fly to uncompressed FLAC container.
    Supports Apple Music, Spotify, YouTube, and Tidal links.
    """
    raw_url = (command.args or "").strip()
    if not raw_url:
        usage_text = (
            "<b>Apple Music FLAC Lossless Downloader</b>\n\n"
            "<b>Usage:</b>\n"
            "<code>/flac &lt;Apple Music / Spotify / YouTube URL&gt;</code>\n\n"
            "• <b>Audio Quality:</b> 100% Bit-Perfect FLAC (Free Lossless Audio Codec)\n"
            "• <b>Features:</b> Full Vorbis comments + embedded high-resolution album cover art\n"
            "• <b>Compatibility:</b> Native playback on Android, Foobar2000, Linux, DAPs, and car stereos."
        )
        try:
            await msg.answer(usage_text, parse_mode="HTML")
        except Exception:
            pass
        return

    # Check cross-platform URL
    url = raw_url
    cross_info = converters.is_cross_platform_url(url)
    if cross_info:
        platform, _ = cross_info
        status_msg = await msg.answer(f"🔄 <b>Resolving {platform.capitalize()} link...</b>", parse_mode="HTML")
        resolved_url, meta = await converters.resolve_cross_platform_link(url)
        if not resolved_url:
            await status_msg.edit_text(f"❌ Could not match this {platform.capitalize()} link on Apple Music.", parse_mode="HTML")
            return
        matched_title = (meta or {}).get("matched_title") or (meta or {}).get("title") or "Track"
        matched_artist = (meta or {}).get("matched_artist") or (meta or {}).get("artist") or "Artist"
        try:
            await status_msg.edit_text(
                f"✨ <b>Matched on Apple Music:</b>\n🎵 <b>{html.escape(matched_title)}</b> — {html.escape(matched_artist)}\n⚡ Fetching FLAC audio...",
                parse_mode="HTML"
            )
        except Exception:
            pass
        url = resolved_url

    user_id_local = msg.from_user.id
    if is_user_busy(user_id_local):
        await msg.answer("⏳ You already have a download in progress. Please wait until it's finished.")
        return

    user_in_queue.add(user_id_local)
    user_pending_jobs[user_id_local] = 1
    position = download_queue.qsize()
    quit_kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🛑 Cancel / Manage Queue", callback_data=f"manage_cancel:{user_id_local}")]
    ])
    await msg.answer(f"🎼 Queued in FLAC mode (position #{position + 1}).", reply_markup=quit_kb)

    await download_queue.put({
        "url": url,
        "msg": msg,
        "user_id": user_id_local,
        "download_mode": "tracks",
        "format_type": "flac"
    })


@dp.message(Command("mp3"))
async def mp3_download_command(msg: types.Message, command: CommandObject) -> None:
    """
    Handles /mp3 command: downloads studio master and transcodes on-the-fly to 320kbps MP3.
    Supports Apple Music, Spotify, YouTube, and Tidal links.
    """
    raw_url = (command.args or "").strip()
    if not raw_url:
        usage_text = (
            "<b>Apple Music MP3 Downloader</b>\n\n"
            "<b>Usage:</b>\n"
            "<code>/mp3 &lt;Apple Music / Spotify / YouTube URL&gt;</code>\n\n"
            "• <b>Audio Quality:</b> Pristine 320kbps MP3 (LAME CBR)\n"
            "• <b>Features:</b> Full ID3v2.3 tags + embedded album cover art (APIC)\n"
            "• <b>Universal Compatibility:</b> Plays on virtually all devices, car stereos, and media players."
        )
        try:
            await msg.answer(usage_text, parse_mode="HTML")
        except Exception:
            pass
        return

    # Check cross-platform URL
    url = raw_url
    cross_info = converters.is_cross_platform_url(url)
    if cross_info:
        platform, _ = cross_info
        status_msg = await msg.answer(f"🔄 <b>Resolving {platform.capitalize()} link...</b>", parse_mode="HTML")
        resolved_url, meta = await converters.resolve_cross_platform_link(url)
        if not resolved_url:
            await status_msg.edit_text(f"❌ Could not match this {platform.capitalize()} link on Apple Music.", parse_mode="HTML")
            return
        matched_title = (meta or {}).get("matched_title") or (meta or {}).get("title") or "Track"
        matched_artist = (meta or {}).get("matched_artist") or (meta or {}).get("artist") or "Artist"
        try:
            await status_msg.edit_text(
                f"✨ <b>Matched on Apple Music:</b>\n🎵 <b>{html.escape(matched_title)}</b> — {html.escape(matched_artist)}\n⚡ Fetching MP3 audio...",
                parse_mode="HTML"
            )
        except Exception:
            pass
        url = resolved_url

    user_id_local = msg.from_user.id
    if is_user_busy(user_id_local):
        await msg.answer("⏳ You already have a download in progress. Please wait until it's finished.")
        return

    user_in_queue.add(user_id_local)
    user_pending_jobs[user_id_local] = 1
    position = download_queue.qsize()
    quit_kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🛑 Cancel / Manage Queue", callback_data=f"manage_cancel:{user_id_local}")]
    ])
    await msg.answer(f"🎵 Queued in MP3 (320k) mode (position #{position + 1}).", reply_markup=quit_kb)

    await download_queue.put({
        "url": url,
        "msg": msg,
        "user_id": user_id_local,
        "download_mode": "tracks",
        "format_type": "mp3"
    })


@dp.message(Command("settings"))
async def settings_command(msg: types.Message) -> None:
    """
    Displays user quality preference options.
    """
    user_id = msg.from_user.id
    current_fmt = "alac"
    try:
        async with async_session() as session:
            current_fmt = await crud.get_user_preferred_format(session, user_id)
    except Exception:
        pass

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=f"{'✅ ' if current_fmt == 'alac' else ''}🎛 ALAC Lossless", callback_data="set_fmt:alac"),
        InlineKeyboardButton(text=f"{'✅ ' if current_fmt == 'flac' else ''}🎼 FLAC Lossless", callback_data="set_fmt:flac"),
    )
    kb.row(
        InlineKeyboardButton(text=f"{'✅ ' if current_fmt == 'mp3' else ''}🎵 MP3 320k", callback_data="set_fmt:mp3"),
        InlineKeyboardButton(text=f"{'✅ ' if current_fmt == 'aac' else ''}🎧 AAC 256k", callback_data="set_fmt:aac"),
    )
    kb.row(
        InlineKeyboardButton(text=f"{'✅ ' if current_fmt == 'atmos' else ''}🌌 Dolby Atmos", callback_data="set_fmt:atmos"),
    )

    text = (
        "⚙️ <b>Download & Audio Quality Settings</b>\n\n"
        f"Current default format: <b>{current_fmt.upper()}</b>\n\n"
        "Choose your preferred audio format. When you send any link directly to the bot, it will automatically download in this format:"
    )
    await msg.answer(text, reply_markup=kb.as_markup(), parse_mode="HTML")


@dp.callback_query(F.data.startswith("set_fmt:"))
async def handle_set_format(call: types.CallbackQuery) -> None:
    """
    Saves user quality preference.
    """
    new_fmt = call.data.split(":")[1]
    user_id = call.from_user.id
    try:
        async with async_session() as session:
            saved_fmt = await crud.set_user_preferred_format(session, user_id, new_fmt)
    except Exception:
        saved_fmt = new_fmt

    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text=f"{'✅ ' if saved_fmt == 'alac' else ''}🎛 ALAC Lossless", callback_data="set_fmt:alac"),
        InlineKeyboardButton(text=f"{'✅ ' if saved_fmt == 'flac' else ''}🎼 FLAC Lossless", callback_data="set_fmt:flac"),
    )
    kb.row(
        InlineKeyboardButton(text=f"{'✅ ' if saved_fmt == 'mp3' else ''}🎵 MP3 320k", callback_data="set_fmt:mp3"),
        InlineKeyboardButton(text=f"{'✅ ' if saved_fmt == 'aac' else ''}🎧 AAC 256k", callback_data="set_fmt:aac"),
    )
    kb.row(
        InlineKeyboardButton(text=f"{'✅ ' if saved_fmt == 'atmos' else ''}🌌 Dolby Atmos", callback_data="set_fmt:atmos"),
    )

    text = (
        "⚙️ <b>Download & Audio Quality Settings</b>\n\n"
        f"Default format updated to: <b>{saved_fmt.upper()}</b>\n\n"
        "All future direct link downloads will use this format."
    )
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        await call.answer(f"✅ Preferred format set to {saved_fmt.upper()}!", show_alert=False)
    except Exception:
        pass


@dp.message(Command("search", "s"))
async def search_command(msg: types.Message, command: CommandObject) -> None:
    """
    Handles /search <query> and /s <query> command:
    Searches both PostgreSQL cached tracks and the live Apple Music catalog,
    presenting interactive 1-tap download/play buttons.
    """
    raw_query = (command.args or "").strip()
    if not raw_query:
        usage_text = (
            "🔍 <b>Apple Music & Library Search</b>\n\n"
            "Search across cached tracks and the full Apple Music catalog directly in this chat!\n\n"
            "<b>Usage:</b>\n"
            "• <code>/search &lt;song title, artist, or album&gt;</code>\n"
            "• <code>/s &lt;query&gt;</code>\n\n"
            "<b>Examples:</b>\n"
            "• <code>/search Starboy</code>\n"
            "• <code>/s Cruel Summer Taylor Swift</code>\n"
            "• <code>/search After Hours The Weeknd</code>\n\n"
            "<i>💡 Tip: You can also search live from any chat by typing <code>@applemusicdw_bot &lt;song&gt;</code></i>"
        )
        await msg.answer(usage_text, parse_mode="HTML")
        return

    status_msg = await msg.answer(f"🔍 <i>Searching for '<b>{html.escape(raw_query)}</b>'...</i>", parse_mode="HTML")

    search_items = []
    seen_song_ids = set()

    # 1. Search PostgreSQL cached database tracks
    try:
        async with async_session() as session:
            search_pat = f"%{raw_query.lower()}%"
            stmt = (
                select(Tracks)
                .where(
                    Tracks.file_id.is_not(None),
                    or_(
                        Tracks.title.ilike(search_pat),
                        Tracks.artist.ilike(search_pat),
                        Tracks.album.ilike(search_pat),
                    )
                )
                .order_by(desc(Tracks.updated_at))
                .limit(5)
            )
            cached_tracks = (await session.exec(stmt)).all()
            for t in cached_tracks:
                if t.song_id and t.song_id not in seen_song_ids:
                    seen_song_ids.add(t.song_id)
                    search_items.append({
                        "id": t.song_id,
                        "title": t.title or "Unknown Track",
                        "artist": t.artist or "Unknown Artist",
                        "album": t.album or "Unknown Album",
                        "is_cached": True,
                    })
    except Exception as dbe:
        print(f"Error querying DB in /search: {dbe}")

    # 2. Search live Apple Music catalog via API
    try:
        api = await gamdlHelpUrl.get_api()
        raw_res = await api.get_search_results(raw_query, limit=8)
        songs_data = (raw_res.get("results", {}) if isinstance(raw_res, dict) else {}).get("songs", {}).get("data", [])
        for s in songs_data:
            sid = s.get("id")
            if sid and sid not in seen_song_ids:
                seen_song_ids.add(sid)
                attrs = s.get("attributes", {})
                search_items.append({
                    "id": sid,
                    "title": attrs.get("name", "Unknown Song"),
                    "artist": attrs.get("artistName", "Unknown Artist"),
                    "album": attrs.get("albumName", "Unknown Album"),
                    "is_cached": False,
                })
    except Exception as ame:
        print(f"Error querying Apple Music in /search: {ame}")

    if not search_items:
        try:
            await status_msg.edit_text(
                f"❌ No matching tracks found for '<b>{html.escape(raw_query)}</b>'.\n\n"
                f"<i>Try searching with different keywords, artist name, or song title.</i>",
                parse_mode="HTML"
            )
        except Exception:
            pass
        return

    # 3. Format response message & buttons
    res_lines = [
        f"🔍 <b>Search Results for:</b> <code>{html.escape(raw_query)}</code>\n",
        "Tap a button below to download or play instantly:\n"
    ]
    buttons = []
    for idx, item in enumerate(search_items[:8], 1):
        badge = "⚡" if item["is_cached"] else "🎵"
        clean_t = item['title'][:26] + ("…" if len(item['title']) > 26 else "")
        clean_a = item['artist'][:18] + ("…" if len(item['artist']) > 18 else "")
        btn_label = f"{badge} {idx}. {clean_t} — {clean_a}"

        status_tag = " [Cached]" if item["is_cached"] else ""
        res_lines.append(f"<b>{idx}.</b> {badge} <b>{html.escape(item['title'])}</b> — <i>{html.escape(item['artist'])}</i>{status_tag}")
        buttons.append([InlineKeyboardButton(text=btn_label, callback_data=f"sdl:{item['id']}")])

    buttons.append([
        InlineKeyboardButton(text="🌐 Web Vault", url="https://stream.eepy.in/"),
        InlineKeyboardButton(text="🗑 Close", callback_data="search_close")
    ])

    try:
        await status_msg.edit_text(
            "\n".join(res_lines),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"Failed to edit search status message: {e}")


@dp.callback_query(F.data.startswith("sdl:"))
async def handle_search_download_callback(call: types.CallbackQuery) -> None:
    """
    Handles clicking a song in /search results:
    Delivers immediately from cache if available, or queues clean download.
    """
    song_id = call.data.split(":", 1)[1].strip()
    await call.answer("⏳ Processing track selection...", show_alert=False)
    user_id_local = call.from_user.id

    if is_user_busy(user_id_local):
        await call.message.answer("⏳ You already have an active download task in progress. Please wait until it completes.")
        return

    # 1. Instant delivery if already cached in Tracks DB!
    async with async_session() as session:
        stmt = select(Tracks).where(Tracks.song_id == str(song_id), Tracks.file_id.is_not(None))
        track = (await session.exec(stmt)).first()
        if track and track.file_id:
            try:
                caption_text = (
                    f"🎵 <b>{html.escape(track.title or 'Unknown')}</b>\n"
                    f"👤 <b>{html.escape(track.artist or 'Unknown Artist')}</b>\n"
                    f"💿 <i>{html.escape(track.album or '')}</i>\n"
                    f"⚡ <i>Delivered from cache (ALAC Lossless)</i>"
                )
                from utils import bot
                await bot.send_audio(
                    chat_id=user_id_local,
                    audio=track.file_id,
                    caption=caption_text,
                    parse_mode="HTML"
                )
                await crud.log_download(
                    session=session,
                    user_id=user_id_local,
                    song_id=str(song_id),
                    format_type="alac",
                    size=track.size or 0,
                    is_cached=True
                )
                await session.commit()
                return
            except Exception as e:
                print(f"Failed to deliver cached search audio {song_id}: {e}")

    # 2. Not cached: queue download using Apple Music song URL
    target_url = f"https://music.apple.com/song/{song_id}"
    user_in_queue.add(user_id_local)
    user_pending_jobs[user_id_local] = 1
    position = download_queue.qsize()

    async with async_session() as session:
        pref_fmt = await crud.get_user_preferred_format(session, user_id_local)

    await download_queue.put({
        "url": target_url,
        "msg": call.message,
        "user_id": user_id_local,
        "format_type": "alac"
    })
    quit_kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🛑 Cancel / Manage Queue", callback_data=f"manage_cancel:{user_id_local}")]
    ])
    await call.message.answer(
        f"✅ Queued download in <b>{pref_fmt.upper()}</b> at position #{position + 1}. Live progress will update below:",
        reply_markup=quit_kb,
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "search_close")
async def handle_search_close(call: types.CallbackQuery) -> None:
    """Closes / removes search results widget."""
    try:
        await call.message.delete()
    except Exception:
        pass


@dp.inline_query()
async def handle_inline_query(inline_query: types.InlineQuery) -> None:
    """
    Handles Telegram inline search queries (@your_bot <query>).
    1. If query is empty: returns recent cached tracks from PostgreSQL.
    2. If query is provided:
       - Searches PostgreSQL cached tracks (instant 1-tap playback via audio_file_id)
       - Searches Apple Music API catalog for uncached tracks (provides 1-tap download deep link)
    """
    query_str = (inline_query.query or "").strip()
    results = []
    seen_song_ids = set()

    try:
        # 1. Search cached tracks in PostgreSQL
        async with async_session() as session:
            if not query_str or len(query_str) < 2:
                stmt = (
                    select(Tracks)
                    .where(Tracks.file_id.is_not(None))
                    .order_by(desc(Tracks.updated_at))
                    .limit(15)
                )
            else:
                search_pattern = f"%{query_str.lower()}%"
                stmt = (
                    select(Tracks)
                    .where(
                        Tracks.file_id.is_not(None),
                        or_(
                            Tracks.title.ilike(search_pattern),
                            Tracks.artist.ilike(search_pattern),
                            Tracks.album.ilike(search_pattern),
                            Tracks.isrc.ilike(search_pattern),
                        )
                    )
                    .order_by(desc(Tracks.updated_at))
                    .limit(10)
                )

            cached_tracks = (await session.exec(stmt)).all()

            for t in cached_tracks:
                if not t.file_id or t.song_id in seen_song_ids:
                    continue
                seen_song_ids.add(t.song_id)

                clean_title = t.title or "Unknown Track"
                clean_artist = t.artist or "Unknown Artist"
                clean_album = t.album or "Unknown Album"

                caption_text = (
                    f"🎵 <b>{html.escape(clean_title)}</b>\n"
                    f"👤 <b>{html.escape(clean_artist)}</b>\n"
                    f"💿 <i>{html.escape(clean_album)}</i>\n"
                    f"⚡ <i>Lossless Audio (ALAC)</i>"
                )

                results.append(
                    InlineQueryResultAudio(
                        id=f"cached_{t.song_id}",
                        audio_file_id=t.file_id,
                        title=f"⚡ [CACHED] {clean_title}",
                        performer=clean_artist,
                        caption=caption_text,
                        parse_mode="HTML"
                    )
                )

        # 2. If query provided, search Apple Music catalog for uncached tracks
        if query_str and len(query_str) >= 2 and len(results) < 15:
            try:
                api = await gamdlHelpUrl.get_api()
                raw_res = await api.get_search_results(query_str, limit=10)
                songs_data = (raw_res.get("results", {}) if isinstance(raw_res, dict) else {}).get("songs", {}).get("data", [])

                bot_info = await inline_query.bot.get_me()
                bot_username = bot_info.username or "applemusicdw_bot"

                for s in songs_data:
                    sid = s.get("id")
                    if not sid or sid in seen_song_ids:
                        continue
                    seen_song_ids.add(sid)

                    attrs = s.get("attributes", {})
                    s_name = attrs.get("name", "Unknown Song")
                    s_artist = attrs.get("artistName", "Unknown Artist")
                    s_album = attrs.get("albumName", "Unknown Album")
                    s_url = attrs.get("url", "")
                    artwork_url = gamdlHelpUrl.get_artwork_url(attrs.get("artwork"), size=300)

                    deeplink_param = encode_deeplink_url(s_url)
                    download_url = f"https://t.me/{bot_username}?start={deeplink_param}"

                    msg_text = (
                        f"🎵 <b>{html.escape(s_name)}</b>\n"
                        f"👤 <b>{html.escape(s_artist)}</b>\n"
                        f"💿 <b>{html.escape(s_album)}</b>\n\n"
                        f"🔗 {s_url}"
                    )

                    article_kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📥 Download via Bot", url=download_url)],
                        [InlineKeyboardButton(text="🌐 Web Vault", url="https://stream.eepy.in/")]
                    ])

                    results.append(
                        InlineQueryResultArticle(
                            id=f"am_{sid}",
                            title=f"📥 {s_name}",
                            description=f"{s_artist} • {s_album} (Tap to download)",
                            thumbnail_url=artwork_url,
                            input_message_content=InputTextMessageContent(
                                message_text=msg_text,
                                parse_mode="HTML"
                            ),
                            reply_markup=article_kb
                        )
                    )
            except Exception as am_err:
                print(f"Error querying Apple Music catalog in inline query: {am_err}")

        await inline_query.answer(
            results=results,
            cache_time=30,
            is_personal=False
        )
    except Exception as e:
        print(f"Inline query error: {e}")
        try:
            await inline_query.answer(results=[], cache_time=5)
        except Exception:
            pass


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
            cached_zip_id, cached_gofile_url, cached_zip_size = await crud.get_cached_album_zip(session, album_id, format_type=fmt)
            size_line = f"\n💾 <b>Size:</b> {utils.human_size(cached_zip_size)}" if cached_zip_size else ""
            gf_line = f"\n🌐 <b>Fast Download (GoFile):</b> <a href='{cached_gofile_url}'>High-Speed Link</a>" if cached_gofile_url else ""
            gf_markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🌐 Fast Download (GoFile)", url=cached_gofile_url)]]) if cached_gofile_url else None
            delivered = False
            if cached_zip_id:
                try:
                    await call.message.edit_text("⚡ Delivering cached album ZIP...")
                    await orig_msg.answer_document(
                        document=cached_zip_id,
                        caption=f"📦 <b>{album_title}</b> ({fmt.upper()})\n👤 <i>{artist}</i>{size_line}{gf_line}\n⚡ <i>Delivered from cache</i>",
                        parse_mode="HTML",
                        reply_markup=gf_markup
                    )
                    await call.message.edit_text("✅ Album ZIP delivered from cache!")
                    delivered = True
                except Exception as e:
                    print(f"Failed to deliver cached zip document {cached_zip_id}: {e}")

            if not delivered and cached_gofile_url:
                try:
                    await call.message.edit_text(
                        f"✅ <b>{album_title}</b> ({fmt.upper()})\n"
                        f"👤 <i>{artist}</i>{size_line}\n\n"
                        f"⚡ <i>Delivered from cache:</i>\n"
                        f"🌐 <a href='{cached_gofile_url}'><b>Download Album ZIP on GoFile</b></a>",
                        parse_mode="HTML",
                        reply_markup=gf_markup
                    )
                    delivered = True
                except Exception:
                    pass

            if delivered:
                return

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
        format_label = fmt.upper()
        try:
            await call.message.edit_text(f"Queued {format_label} album in {mode.upper()} mode (starting at position {pos + 1})...")
        except Exception:
            pass
        await download_queue.put({
            "url": url,
            "msg": orig_msg,
            "user_id": user_id,
            "status_msg": call.message,
            "download_mode": mode,
            "album_id": album_id,
            "songs": songs,
            "format_type": fmt
        })


async def deliver_single_default_track(
    file_path: str,
    msg,
    songs: list,
    user_id_local: int,
    status_msg,
    cancel_builder,
    total_tracks: int,
    completed_count: int,
    download_mode: str,
    task: dict,
) -> bool:
    import secrets
    async with async_session() as session:
        result = await session.exec(select(User).where(User.user_id == user_id_local))
        user = result.first()
        
        if user and not user.is_premium and msg:
            alac_count = await crud.get_alac_download_count_12h(session, user_id_local)
            if alac_count >= 100:
                try:
                    await msg.answer("❌ ALAC download limit reached (100 tracks per 12 hours). Stopping further downloads.")
                except Exception:
                    pass
                return False

        # Check if transcoding is requested (FLAC or MP3)
        requested_fmt = str(task.get("format_type", "alac")).lower().strip()
        orig_file_path = file_path
        if requested_fmt in ("flac", "mp3"):
            transcoded_path = await utils.transcode_audio(file_path, target_format=requested_fmt, remove_source=False)
            if transcoded_path and os.path.exists(transcoded_path):
                file_path = transcoded_path

        # Extract metadata and upload
        track_title, artist, thumbnail, duration, isrc = await asyncio.to_thread(
            utils.extract_track_metadata, file_path
        )
        
        sent_msg = None
        saved_chat_id = utils.STORAGE_CHANNEL_ID
        saved_message_id = None
        if msg:
            sent_msg, saved_chat_id, saved_message_id = await utils.upload_and_deliver_audio(
                bot=msg.bot,
                user_chat_id=msg.chat.id,
                file_path=file_path,
                title=track_title,
                performer=artist,
                thumbnail=thumbnail,
                duration=duration
            )

        if user:
            user.download_count += 1
            session.add(user)
            await session.commit()

        # Real-Time Progress Bar Update
        if status_msg:
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

        media_obj = (sent_msg.audio or sent_msg.document) if sent_msg else None
        file_id_val = media_obj.file_id if media_obj else f"cached_{secrets.token_hex(8)}"
        file_uniq_val = media_obj.file_unique_id if media_obj else f"uniq_{secrets.token_hex(8)}"
        file_sz_val = getattr(media_obj, "file_size", 0) if media_obj else (os.path.getsize(file_path) if os.path.exists(file_path) else 0)

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
        if isrc and songs:
            for original_track in songs:
                if original_track.isrc == isrc:
                    track_input = schema.TrackInputSchema(**original_track.model_dump())
                    track_input.file_id = tbot.file_id
                    track_input.file_unique_id = tbot.file_unique_id
                    track_input.size = tbot.size
                    track_input.chat_id = tbot.chat_id
                    track_input.message_id = tbot.message_id
                    await crud.save_single_track(session=session, track_data=track_input, format_type="alac")
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

        if not matched and songs:
            for original_track in songs:
                if utils.convert_text(original_track.title) == utils.convert_text(tbot.title):
                    track_input = schema.TrackInputSchema(**original_track.model_dump())
                    track_input.file_id = tbot.file_id
                    track_input.file_unique_id = tbot.file_unique_id
                    track_input.size = tbot.size
                    track_input.chat_id = tbot.chat_id
                    track_input.message_id = tbot.message_id
                    await crud.save_single_track(session=session, track_data=track_input, format_type="alac")
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
                if orig_file_path != file_path and os.path.exists(orig_file_path):
                    await asyncio.to_thread(os.remove, orig_file_path)
            except Exception as e:
                print(f"Failed to delete {file_path}: {e}")

        return True


async def process_download(task: dict) -> None:
    """
    Core logic for processing a download request: fetching metadata, checking cache, downloading via gamdl, and uploading to Telegram.
    Supports 'tracks', 'zip', and 'both' delivery modes.
    """
    message = task["url"]  # The specific target album/track URL
    msg: Optional[Message] = task.get("msg")  # The aiogram message context used to reply
    user_id_local = task.get("user_id", 999999999)
    download_mode = task.get("download_mode", "tracks")
    album_id_task = task.get("album_id")
    is_admin_cache = task.get("is_admin_cache", False) or (msg is None)

    import secrets
    if msg and hasattr(msg, "message_id"):
        unique_task_id = f"{msg.message_id}_{int(asyncio.get_event_loop().time() * 1000)}"
    else:
        unique_task_id = f"cache_{int(asyncio.get_event_loop().time() * 1000)}_{secrets.token_hex(4)}"

    cancel_builder = InlineKeyboardBuilder()
    cancel_builder.row(types.InlineKeyboardButton(text="✖ Cancel Download", callback_data=f"cancel_download:{unique_task_id}"))

    status_msg = task.get("status_msg")
    if msg:
        if not status_msg:
            try:
                status_msg = await msg.answer('🔍 Processing request...', reply_markup=cancel_builder.as_markup())
            except Exception:
                status_msg = None
        else:
            try:
                await status_msg.edit_text('🔍 Processing request...', reply_markup=cancel_builder.as_markup())
            except Exception:
                pass

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
                cached_zip_fid, cached_gofile_url, cached_zip_size = await crud.get_cached_album_zip(session, album_id, format_type="alac")
                size_line = f"\n💾 <b>Size:</b> {utils.human_size(cached_zip_size)}" if cached_zip_size else ""
                gf_line = f"\n🌐 <b>Fast Download (GoFile):</b> <a href='{cached_gofile_url}'>High-Speed Link</a>" if cached_gofile_url else ""
                gf_markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🌐 Fast Download (GoFile)", url=cached_gofile_url)]]) if cached_gofile_url else None
                delivered = False
                if cached_zip_fid:
                    try:
                        await msg.answer_document(
                            document=cached_zip_fid,
                            caption=f"📦 <b>{songs[0].album}</b> (Lossless ALAC)\n👤 <i>{songs[0].artist}</i>{size_line}{gf_line}\n⚡ <i>Delivered from cache</i>",
                            parse_mode="HTML",
                            reply_markup=gf_markup
                        )
                        await status_msg.edit_text("✅ Album ZIP delivered from cache!")
                        delivered = True
                    except Exception as e:
                        print(f"Failed to deliver cached ALAC zip document: {e}")

                if not delivered and cached_gofile_url:
                    try:
                        await msg.answer(
                            f"📦 <b>{songs[0].album}</b> (Lossless ALAC)\n"
                            f"👤 <i>{songs[0].artist}</i>{size_line}\n\n"
                            f"⚡ <i>Delivered from cache:</i>\n"
                            f"🌐 <a href='{cached_gofile_url}'><b>Download Album ZIP on GoFile</b></a>",
                            parse_mode="HTML",
                            reply_markup=gf_markup
                        )
                        await status_msg.edit_text("✅ Cached Album ZIP link delivered!")
                        delivered = True
                    except Exception as e:
                        print(f"Failed to deliver cached ALAC GoFile link: {e}")

                if delivered:
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

        if unique_task_id in active_tasks:


            active_tasks[unique_task_id]["async_task"] = asyncio.current_task()



        already_processed = set()



        async def on_track_downloaded(item, file_path: str):


            nonlocal completed_count


            if not file_path or not os.path.exists(file_path):


                return


            if file_path in already_processed:


                return


            already_processed.add(file_path)



            if download_mode == "zip":


                completed_count += 1


                if status_msg:


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


                return



            completed_count += 1


            can_continue = await deliver_single_default_track(


                file_path=file_path,


                msg=msg,


                songs=songs,


                user_id_local=user_id_local,


                status_msg=status_msg,


                cancel_builder=cancel_builder,


                total_tracks=total_tracks,


                completed_count=completed_count,


                download_mode=download_mode,


                task=task,


            )


            if not can_continue:


                if unique_task_id in active_tasks:


                    active_tasks[unique_task_id]["cancelled"] = True



        format_type = str(task.get("format_type", "lossless")).lower().strip()
        try:
            await audio_service.download_audio(
                urls=target_dl_urls,
                format_type=format_type,


                output_dir=task_output_dir,


                temp_dir=task_temp_dir,


                cookies_path=cookies_path,


                on_track_done=on_track_downloaded,


                is_cancelled=lambda: active_tasks.get(unique_task_id, {}).get("cancelled", False),


            )


        except Exception as e:


            err_msg = audio_service.format_gamdl_error(e)


            print(f"🛑 In-memory download failed for {unique_task_id}: {e}")


            if status_msg and not active_tasks.get(unique_task_id, {}).get("cancelled"):


                try:


                    await status_msg.edit_text(f"❌ Download Failed\n\n{err_msg}")


                except Exception:


                    pass


            return

        # Check if task was cancelled while process was terminating
        if active_tasks.get(unique_task_id, {}).get("cancelled"):
            return

        # Handle ZIP Generation & Delivery for 'zip' and 'both' modes (only if files were downloaded)
        if download_mode in ("zip", "both") and len(already_processed) > 0:
            try:
                await status_msg.edit_text("📦 Packaging album into ZIP with max-res cover and lyrics (.lrc)...")
            except Exception:
                pass

            # Save cover art and all lyric formats into folder
            await utils.save_album_cover_and_lyrics(songs, task_output_dir)

            # Transcode all album tracks to target format if FLAC or MP3 is requested
            requested_fmt = str(task.get("format_type", "alac")).lower().strip()
            if requested_fmt in ("flac", "mp3"):
                for root, _, files in os.walk(task_output_dir):
                    for f in files:
                        if f.endswith(".m4a"):
                            orig_m4a = os.path.join(root, f)
                            await utils.transcode_audio(orig_m4a, target_format=requested_fmt, remove_source=True)
                fmt_label = requested_fmt.upper()
            else:
                fmt_label = "Lossless ALAC"

            # Build ZIP archive
            album_title = songs[0].album or "Album"
            artist = songs[0].artist or "Unknown Artist"
            clean_album = re.sub(r'[\\/*?:"<>|]', "", album_title)
            clean_artist = re.sub(r'[\\/*?:"<>|]', "", artist)
            zip_filename = f"{clean_artist} - {clean_album} [{fmt_label}].zip"
            zip_path = os.path.join(os.path.dirname(task_output_dir), zip_filename)

            await utils.create_album_zip(task_output_dir, zip_path)
            zip_size = os.path.getsize(zip_path) if os.path.exists(zip_path) else 0

            caption = (
                f"📦 <b>{album_title}</b> ({fmt_label})\n"
                f"👤 <i>{artist}</i>\n"
                f"💾 <b>Size:</b> {utils.human_size(zip_size)}\n"
                f"🎵 {len(songs)} Tracks • Max-Res Cover • Lyrics (.lrc)"
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

            sent_doc, saved_cid, saved_mid, zip_fid, gofile_url, uploaded_zip_size = await utils.upload_and_deliver_zip_document(
                bot=msg.bot,
                user_chat_id=msg.chat.id,
                file_path=zip_path,
                caption=caption,
                thumbnail=thumb_data
            )
            final_zip_size = uploaded_zip_size or zip_size

            # Save cached ZIP file_id, gofile_url, and file size
            alb_id_save = album_id or (songs[0].album_id if songs else None)
            if alb_id_save:
                async with async_session() as session:
                    await crud.save_cached_album_zip(
                        session=session,
                        album_id=alb_id_save,
                        album_name=album_title,
                        artist=artist,
                        format_type="alac",
                        zip_file_id=zip_fid,
                        gofile_url=gofile_url,
                        zip_size=final_zip_size
                    )

            if gofile_url and not zip_fid and msg:
                try:
                    await msg.answer(
                        f"📦 <b>{album_title}</b> (Lossless ALAC)\n"
                        f"👤 <i>{artist}</i>\n"
                        f"💾 <b>Size:</b> {utils.human_size(final_zip_size)}\n\n"
                        f"⚡ <i>File size exceeds 2GB Telegram limit. Uploaded to GoFile:</i>\n"
                        f"🌐 <a href='{gofile_url}'><b>Download Album ZIP on GoFile</b></a>",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

            if os.path.exists(zip_path):
                try:
                    os.remove(zip_path)
                except Exception:
                    pass

            if status_msg:
                try:
                    if len(already_processed) < total_tracks:
                        await status_msg.edit_text(
                            f"⚠️ <b>Partial Album Completed:</b> {len(already_processed)}/{total_tracks} tracks packaged.\n"
                            f"Some tracks failed to download from Apple Music.\n\n"
                            f"🌐 Link can also be downloaded at: https://stream.eepy.in/",
                            parse_mode="HTML"
                        )
                    else:
                        await status_msg.edit_text("✅ Album download and packaging completed successfully!\n\n🌐 Link can also be downloaded at: https://stream.eepy.in/")
                except Exception:
                    pass
            return

        if not active_tasks.get(unique_task_id, {}).get("cancelled"):
            if status_msg:
                if len(already_processed) == 0:
                    try:
                        await status_msg.edit_text(
                            "❌ Download Failed\n\n"
                            "The requested track or album could not be downloaded from Apple Music.\n\n"
                            "👉 Try downloading in AAC using /aac <link> or try another song."
                        )
                    except Exception:
                        pass
                elif len(already_processed) < total_tracks:
                    try:
                        await status_msg.edit_text(
                            f"⚠️ Partially Completed: {len(already_processed)}/{total_tracks} tracks delivered.\n"
                            f"Some tracks failed to download from Apple Music.\n\n"
                            f"🌐 Downloaded tracks: https://stream.eepy.in/"
                        )
                    except Exception:
                        pass
                else:
                    try:
                        await status_msg.edit_text("✅ All tracks processed successfully.\n\n🌐 Link can be downloaded at: https://stream.eepy.in/")
                    except Exception:
                        pass

    except Exception as e:
        print(f"Error handling download: {e}")
        if msg:
            try:
                await msg.answer(f"⚠️ An unexpected error occurred. {str(e)}")
            except Exception:
                pass
    finally:
        active_tasks.pop(unique_task_id, None)
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
        try:
            while bot_control.is_bot_paused:
                await asyncio.sleep(1)

            task = await download_queue.get()
            msg = task.get("msg") or task.get("message")
            user_id = task.get("user_id")
            if not user_id and msg and hasattr(msg, "from_user") and msg.from_user:
                user_id = msg.from_user.id
            if not user_id:
                user_id = 999999999

            user_lock = user_locks.setdefault(user_id, asyncio.Lock())

            async with user_lock:
                try:
                    if msg:
                        # Check database limit before starting download subprocess
                        async with async_session() as session:
                            result = await session.exec(select(User).where(User.user_id == user_id))
                            user = result.first()
                            if user and not user.is_premium:
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
        except asyncio.CancelledError:
            break
        except Exception as outer_err:
            print(f"[Worker Error] Unexpected error in ALAC worker: {outer_err}")
            await asyncio.sleep(1)


async def scheduled_db_backup_worker() -> None:
    """
    Background worker that runs a daily database backup, uploads to GitHub Releases,
    and delivers the archive to the Telegram Storage Channel automatically every 24 hours.
    """
    # Wait 60 seconds after bot boot before starting
    await asyncio.sleep(60)
    from scripts import backup_db

    while True:
        try:
            logging.info("Starting automated periodic database backup...")
            res = await backup_db.run_backup(send_telegram=True, upload_github=True)
            logging.info(f"Automated DB backup finished successfully: {res.get('file_path')} (GitHub: {res.get('github_url')})")
        except Exception as e:
            logging.error(f"Error during scheduled database backup: {e}")

        # Wait 24 hours before next scheduled backup
        await asyncio.sleep(86400)


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

    # Start periodic database backup task (runs daily)
    asyncio.create_task(scheduled_db_backup_worker())

    # Backfill missing zip file sizes for all previous albums in background
    asyncio.create_task(crud.backfill_missing_zip_sizes(bot))

    # Pre-warm in-memory audio engine in background
    try:
        import audio_service
        asyncio.create_task(audio_service.get_base_interface())
        logging.info("Audio engine pre-warming started.")
    except Exception as e:
        logging.warning(f"Failed to pre-warm audio engine: {e}")

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
            types.BotCommand(command="search", description="Search songs across Apple Music & Database"),
            types.BotCommand(command="flac", description="Download in bit-perfect FLAC format"),
            types.BotCommand(command="mp3", description="Download in 320kbps MP3 format"),
            types.BotCommand(command="settings", description="Configure your preferred audio format"),
            types.BotCommand(command="cancel", description="Quit/clear your queue & start fresh"),
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
    bot_control.bot_instance = bot

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