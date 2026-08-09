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
from gamdlUrl import get_any_url
from queues import download_queue, user_in_queue, user_locks, user_pending_jobs, active_tasks, is_user_busy

from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

load_dotenv()

TOKEN_API = os.getenv("TOKEN_API")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "https://tbot.eepy.in")
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "super_secret_webhook_token_123")
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
STREAM_SERVER_URL = os.getenv("STREAM_SERVER_URL", "https://stream.eepy.in")



LISTEN_HOST = os.getenv("WEBHOOK_LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.getenv("WEBHOOK_LISTEN_PORT", 8080))

dp = Dispatcher()
async_session = get_session_maker()


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
        [InlineKeyboardButton(text="🌐 Web Vault (stream.eepy.in)", url="https://stream.eepy.in/")],
        [InlineKeyboardButton(text="💬 Join Discord Community", url="https://discord.gg/KBy2UMfjx8")],
        [InlineKeyboardButton(text="🔎 Apple Music Storefront Search", url="https://am-l.eepy.in/")]
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
        f"• <b>Daily Limit:</b> 50 downloads per day (cached files do not count)\n\n"
        f"<b>Note:</b> Artist downloads (<code>/artist</code>) are strictly limited to ALAC format.\n\n"
        f"<b>Note:</b> AAC downloads (<code>/aac &lt;url&gt;</code>) AAC 256kbps 44.1kHz.\n\n"
        f"<b>Note:</b> Dolby Atmos downloads (<code>/atmos &lt;url&gt;</code>) Spatial Audio.\n\n"
        f"<b>How to Use</b>\n"
        f"Send any track, album, or artist link directly to this chat.\n\n"
        f"<b>Shortcuts & Commands</b>\n"
        f"• Inline search: @applemusicdw_bot\n"
        f"• Web Vault Streaming: https://stream.eepy.in/\n"
        f"• Storefront Search: https://am-l.eepy.in/\n"
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
    Handles incoming messages by adding them to the download queue if the user doesn't already have a task in progress.
    """
    links = re.findall(r"https?://[^\s<>]+", msg.text)
    if not links:
        return

    if len(links) != 1:
        await msg.answer("Please send exactly one Apple Music link.")
        return

    user_id_local = msg.from_user.id
    if is_user_busy(user_id_local):
        await msg.answer("⏳ You already have a download in progress. Please wait until it's finished.")
        return

    user_in_queue.add(user_id_local)
    user_pending_jobs[user_id_local] = len(links)
    position = download_queue.qsize()
    await msg.answer(f"Queued {len(links)} link(s) (starting at position {position + 1}).")

    for url in links:
        await download_queue.put({
            "url": url,
            "msg": msg,
            "user_id": user_id_local,
        })


async def process_download(task: dict) -> None:
    """
    Core logic for processing a download request: fetching metadata, checking cache, downloading via gamdl, and uploading to Telegram.
    """
    message = task["url"]  # The specific target album/track URL
    msg: Message = task["msg"]  # The aiogram message context used to reply
    user_id_local = task["user_id"]

    unique_task_id = f"{msg.message_id}_{int(asyncio.get_event_loop().time() * 1000)}"
    cancel_builder = InlineKeyboardBuilder()
    cancel_builder.row(types.InlineKeyboardButton(text="✖ Cancel Download", callback_data=f"cancel_download:{unique_task_id}"))

    status_msg = await msg.answer('🔍 Processing request...', reply_markup=cancel_builder.as_markup())
    task_output_dir = os.path.join("./downloads", unique_task_id)
    process = None

    active_tasks[unique_task_id] = {
        "process": None,
        "cancelled": False,
        "user_id": user_id_local,
        "status_msg": status_msg
    }

    try:
        # 1. Fetch metadata from Apple Music
        try:
            songs = await get_any_url(message)
        except Exception as e:
            try:
                await status_msg.edit_text(f"❌ Failed to fetch metadata: {str(e)}")
            except Exception:
                pass
            return

        total_tracks = len(songs)
        completed_count = 0

        # 2. Check database for existing file_ids
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

            # 4. Deliver cached tracks
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

            if not user.is_premium and user.downloaded_today >= user.daily_limit:
                try:
                    await status_msg.edit_text("Daily download limit reached.")
                except Exception:
                    pass
                return

            if not tracks_to_download:
                try:
                    await status_msg.edit_text("✅ All tracks delivered from cache!\n\n🌐 Link can be downloaded at: https://stream.eepy.in/")
                except Exception:
                    pass
                return

        # 5. Download missing tracks using gamdl
        progress_text = (
            f"🚀 {hbold('DOWNLOADING TRACKS')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{make_progress_bar(completed_count, total_tracks)}\n"
            f"📥 Downloading {len(tracks_to_download)} remaining track(s)..."
        )
        try:
            await status_msg.edit_text(progress_text, reply_markup=cancel_builder.as_markup())
        except Exception:
            pass

        task_temp_dir = f"{task_output_dir}_temp"
        await asyncio.to_thread(os.makedirs, task_output_dir, exist_ok=True)
        await asyncio.to_thread(os.makedirs, task_temp_dir, exist_ok=True)
        
        process = await asyncio.create_subprocess_exec(
            "gamdl",
            "--output-path", task_output_dir,
            "--temp-path", task_temp_dir,
            *tracks_to_download,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
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

            line_bytes = await process.stdout.readline()
            if not line_bytes:
                break
            
            line = ansi_escapes.sub("", line_bytes.decode("utf-8", errors="ignore")).strip()
            if line:
                print(f"[gamdl] {line}")

            # Check for finalized .m4a files in output directory (ignoring temp/encrypted files)
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
                    
                    # Check limit before processing
                    async with async_session() as session:
                        result = await session.exec(select(User).where(User.user_id == user_id_local))
                        user = result.one()
                        
                        current_date = datetime.now(timezone.utc).date()
                        if not user.is_premium and user.last_download != current_date:
                            user.downloaded_today = 0
                            user.last_download = current_date
                            session.add(user)
                            await session.commit()

                        if not user.is_premium and user.downloaded_today >= user.daily_limit:
                            try:
                                await msg.answer("❌ Quota exhausted! Stopping further downloads.")
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
                        abs_path = os.path.abspath(file_path)
                        
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
                            if not user.is_premium:
                                user.downloaded_today += 1
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
                                        break

                        
                        try:
                            await asyncio.to_thread(os.remove, file_path)
                            print(f"Deleted local file: {file_path}")
                        except Exception as e:
                            print(f"Failed to delete {file_path}: {e}")

            await asyncio.sleep(1) # Small delay between checks

        return_code = await process.wait()
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
                    current_date = datetime.now(timezone.utc).date()
                    if user:
                        if user.last_download != current_date:
                            user.downloaded_today = 0
                            user.last_download = current_date
                            session.add(user)
                            await session.commit()
                            await session.refresh(user)
                        
                        if not user.is_premium and user.downloaded_today >= user.daily_limit:
                            try:
                                await msg.answer("❌ Daily download limit reached. Skipping queued item.")
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
    Startup handler: initializes database, background workers, and sets the webhook.
    """
    await database.init_db()

    # Start 3 concurrent workers
    for _ in range(3):
        asyncio.create_task(worker())

    # Start 10 concurrent AAC workers
    for _ in range(10):
        asyncio.create_task(aac_worker())

    # Start 10 concurrent Atmos workers
    for _ in range(10):
        asyncio.create_task(atmos_worker())

    # Set webhook on local Telegram API server
    logging.info(f"Setting webhook to: {WEBHOOK_URL}")
    await bot.set_webhook(
        url=WEBHOOK_URL,
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=True,
    )
    logging.info("Webhook successfully configured.")

    # Register bot commands menu
    try:
        await bot.set_my_commands([
            types.BotCommand(command="start", description="Start the bot & landing dashboard"),
            types.BotCommand(command="artist", description="Download artist top tracks or catalog"),
            types.BotCommand(command="aac", description="Download track/album in AAC 256kbps"),
            types.BotCommand(command="atmos", description="Download track/album in Dolby Atmos"),
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
    dp.include_router(aac)
    dp.include_router(atmos)
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

    logging.info(f"Starting webhook web server on {LISTEN_HOST}:{LISTEN_PORT}...")
    web.run_app(app, host=LISTEN_HOST, port=LISTEN_PORT)


def setup_bot_logging():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    # 1. Root logger configuration

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Clean up existing handlers if re-running in interactive environments
    if logger.hasHandlers():
        logger.handlers.clear()

    # 2. Format: includes timestamp, log level, module name, and message
    formatter = logging.Formatter(
        "%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 3. Terminal Handler (Live streaming to console only)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # 4. Attach console handler
    logger.addHandler(console_handler)


if __name__ == "__main__":
    setup_bot_logging()
    main()