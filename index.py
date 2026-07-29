import asyncio, glob, os, re, shutil, logging, sys, crud, database, schema, utils
from datetime import date, datetime, timezone
from logging.handlers import RotatingFileHandler

from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

from aac import aac, aac_worker
from artist import test_router
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import FSInputFile, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.markdown import hbold, hunderline
from sqlmodel import select
from dotenv import load_dotenv
from database import User, get_session_maker
from gamdlUrl import get_any_url
from queues import download_queue, user_in_queue, user_locks, user_pending_jobs

load_dotenv()

TOKEN_API = os.getenv("TOKEN_API")

dp = Dispatcher()
async_session = get_session_maker()

# Queue management for concurrent downloads

@dp.message(CommandStart())
async def cmd_start(msg: types.Message) -> None:
    """
    Renders the elegant main landing dashboard for the bot.
    """
    welcome_text = (
        f"<b>Apple Music Downloader</b>\n"
        f"Download studio-grade Lossless audio directly from Apple Music.\n\n"
        f"<b>Features</b>\n"
        f"• <b>Audio Quality:</b> ALAC Lossless up to 24-bit / 192kHz\n"
        f"• <b>Artist Support:</b> Send an artist link to fetch top tracks or catalogs\n"
        f"• <b>Daily Limit:</b> 50 downloads per day (cached files do not count)\n\n"
        f"<b>Note:</b> Artist downloads (<code>/artist</code>) are strictly limited to ALAC format.\n\n"
        f"<b>Note:</b> AAC downloads (<code>/aac <url></code>) AAC 256kbps 44.1kHz.\n\n"
        f"<b>How to Use</b>\n"
        f"Send any track, album, or artist link directly to this chat.\n\n"
        f"<b>Shortcuts & Commands</b>\n"
        f"• Inline search: @applemusicdw_bot\n"
        f"• View all commands: /help"
    )

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="💎 Upgrade to Premium", callback_data="menu_premium"))
    builder.row(
        types.InlineKeyboardButton(text="🌍 Region Status", callback_data="menu_regions"),
        types.InlineKeyboardButton(text="📖 Guide / FAQ", callback_data="menu_faq")
    )
    builder.row(types.InlineKeyboardButton(text="🔍 Inline Search", switch_inline_query_current_chat=""))

    await msg.answer(
        text=welcome_text,
        # reply_markup=builder.as_markup(),
        parse_mode="HTML"
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
    if user_id_local in user_in_queue:
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
    status_msg = await msg.answer('🔍 Processing request...')

    unique_task_id = f"{msg.message_id}_{int(asyncio.get_event_loop().time() * 1000)}"
    task_output_dir = os.path.join("./downloads", unique_task_id)
    process = None

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
                try:
                    await msg.answer_audio(audio=file_id)
                except Exception:
                    pass
                user.download_count += 1
                session.add(user)
                await session.commit()

            if not user.is_premium and user.downloaded_today >= user.daily_limit:
                try:
                    await status_msg.edit_text("Daily download limit reached.")
                except Exception:
                    pass
                return

            if not tracks_to_download:
                try:
                    await status_msg.edit_text("✅ All tracks delivered from cache!")
                except Exception:
                    pass
                return

        # 5. Download missing tracks using gamdl
        try:
            await status_msg.edit_text(f"🚀 Downloading {len(tracks_to_download)} track(s)...")
        except Exception:
            pass

        await asyncio.to_thread(os.makedirs, task_output_dir, exist_ok=True)
        
        process = await asyncio.create_subprocess_exec(
            "gamdl",
            "--output-path", task_output_dir,
            *tracks_to_download,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        ansi_escapes = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        already_processed = set()

        while True:
            line_bytes = await process.stdout.readline()
            if not line_bytes:
                break
            
            line = ansi_escapes.sub("", line_bytes.decode("utf-8", errors="ignore")).strip()
            if line:
                print(f"[gamdl] {line}")

            # Check for new files in the output directory
            downloaded_files = await asyncio.to_thread(
                glob.glob, f"{task_output_dir}/**/*.m4a*", recursive=True
            )
            for file_path in downloaded_files:
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
                        
                        try:
                            sent_msg = await msg.answer_audio(
                                audio=FSInputFile(abs_path),
                                title=track_title,
                                thumbnail=thumbnail,
                                performer=artist,
                                duration=duration
                            )
                        except Exception as e:
                            print(f"Failed to send audio message: {e}")
                            sent_msg = None

                        if sent_msg:
                            user.download_count += 1
                            if not user.is_premium:
                                user.downloaded_today += 1
                                session.add(user)
                                await session.commit()

                            # Save to cache
                            tbot = schema.TrackInputSchema(
                                file_id=sent_msg.audio.file_id,
                                file_unique_id=sent_msg.audio.file_unique_id,
                                title=track_title,
                                size=sent_msg.audio.file_size,
                                isrc=isrc
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
        if return_code == 0:
            try:
                await status_msg.edit_text("✅ All tracks processed successfully.")
            except Exception:
                pass
        else:
            try:
                await status_msg.edit_text("⚠ Some tracks might have failed to download.")
            except Exception:
                pass

    except Exception as e:
        print(f"Error handling download: {e}")
        try:
            await msg.answer(f"⚠️ An unexpected error occurred. {str(e)}")
        except Exception:
            pass
    finally:
        if process and process.returncode is None:
            try:
                process.terminate()
                await process.wait()
            except ProcessLookupError:
                pass
        if await asyncio.to_thread(os.path.exists, task_output_dir):
            try:
                await asyncio.to_thread(shutil.rmtree, task_output_dir)
            except Exception as e:
                print(f"Failed to delete {task_output_dir}: {e}")


async def worker() -> None:
    """
    Worker function to process the download queue.
    """
    while True:
        task = await download_queue.get()
        user_id = task["user_id"]
        msg = task["msg"]

        user_lock = user_locks.setdefault(user_id, asyncio.Lock())

        async with user_lock:
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
                        download_queue.task_done()
                        remaining = user_pending_jobs.get(user_id, 1) - 1
                        if remaining <= 0:
                            user_pending_jobs.pop(user_id, None)
                            user_in_queue.discard(user_id)
                            user_locks.pop(user_id, None)
                        else:
                            user_pending_jobs[user_id] = remaining
                        continue

            try:
                await process_download(task)
            except Exception as e:
                print(f"Worker caught execution exception: {e}")
            finally:
                download_queue.task_done()
        remaining = user_pending_jobs.get(user_id, 1) - 1
        if remaining <= 0:
            user_pending_jobs.pop(user_id, None)
            user_in_queue.discard(user_id)
            user_locks.pop(user_id, None)
        else:
            user_pending_jobs[user_id] = remaining

async def main() -> None:
    """
    Main entry point for the bot.
    """
    await database.init_db()

    # local_server = TelegramAPIServer.from_base("http://localhost:8081")

    # 2. Use aiogram's AiohttpSession wrapper instead of raw aiohttp
    # session = AiohttpSession(api=local_server)
    #
    # # 3. Initialize bot with the wrapped session
    # bot = Bot(
    #     token=TOKEN_API,
    #     session=session,
    #     default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    # )


    bot = Bot(
        token=TOKEN_API,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp.include_router(test_router)
    dp.include_router(aac)

    # Start 3 concurrent workers
    for _ in range(3):
        asyncio.create_task(worker())

    # Start 10 concurrent AAC workers
    for _ in range(10):
        asyncio.create_task(aac_worker())

    print("Bot is starting...")
    await dp.start_polling(bot)


def setup_bot_logging():
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

    # 3. Terminal Handler (Live streaming)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # 4. File Handler with Rotation (Prevents bot logs from filling up your disk)
    # Rolls over after 5 MB, keeping up to 3 backup files
    file_handler = RotatingFileHandler(
        "bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    # 5. Attach handlers
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)


if __name__ == "__main__":
    setup_bot_logging()
    asyncio.run(main())