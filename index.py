import asyncio
import glob
import os
import re
import shutil
import logging
import sys
from datetime import date
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
import crud
import database
import Schema
import utils
from database import User, get_session_maker
from gamdlUrl import get_any_url
from queues import download_queue, user_in_queue, user_locks

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
        f"✨ {hbold('APPLE MUSIC DOWNLOADER')} ✨\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Your high-fidelity portal for pulling studio-grade audio and crisp cinematic visuals directly from Apple Music.\n\n"
        f"⚡ {hunderline('SUPPORTED FORMATS')}\n"
        f"📂 {hbold('Tracks:')} AAC (256kbps), Spatial Dolby Atmos, Binaural, and pure Lossless ALAC up to 24-bit/192kHz.\n"
        f"🎬 {hbold('Videos:')} Video support coming soon\n\n"
        f"🚀 {hunderline('HOW TO USE')}\n"
        f"Drop up to 3 links simultaneously into this chat.\n\n"
        f"👑 {hunderline('TIER ACCESS')}\n"
        f"• {hbold('Standard tier:')} 30 track downloads daily (AAC profile).\n"
        f"• {hbold('Premium tier:')} Unlimited requests, master-codec suite, and priority processing.\n\n"
        f"💡 {hunderline('SHORTCUTS')}\n"
        f"Trigger instant search by typing: @applemusicdw_bot\n\n"
        f"Explore full features via /help • Check network regions via /countries"
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
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )


@dp.message(Command("test"))
# @dp.message()
async def download_handle(msg: types.Message) -> None:
    """
    Handles incoming messages by adding them to the download queue if the user doesn't already have a task in progress.
    """
    if not msg.text or not msg.text.startswith("http"):
        return

    user_id_local = msg.from_user.id
    if user_id_local in user_in_queue:
        await msg.answer("⏳ You already have a download in progress. Please wait until it's finished.")
        return

    user_in_queue.add(user_id_local)
    position = download_queue.qsize()
    await msg.answer(f"✅ Queued (position {position + 1}).")

    payload = {
        "url": msg.text,
        "msg": msg,
        "user_id": user_id_local
    }
    await download_queue.put(payload)


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

    try:
        # 1. Fetch metadata from Apple Music
        try:
            songs = await get_any_url(message)
        except Exception as e:
            await status_msg.edit_text(f"❌ Failed to fetch metadata: {str(e)}")
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

            if not user.is_premium:
                if user.last_download != date.today():
                    user.downloaded_today = 0
                    user.last_download = date.today()
                    session.add(user)
                    await session.commit()

            # 4. Deliver cached tracks
            for file_id in file_ids:
                if not user.is_premium and user.downloaded_today >= user.daily_limit:
                    await msg.answer("❌ Quota exhausted! Remaining cached tracks cancelled.")
                    break

                sent_msg = await msg.answer_audio(audio=file_id)
                if sent_msg and not user.is_premium:
                    user.downloaded_today += 1
                    session.add(user)
                    await session.commit()

            if not tracks_to_download:
                await status_msg.edit_text("✅ All tracks delivered from cache!")
                return

        # 5. Download missing tracks using gamdl
        await status_msg.edit_text(f"🚀 Downloading {len(tracks_to_download)} track(s)...")
        os.makedirs(task_output_dir, exist_ok=True)
        
        process = await asyncio.create_subprocess_exec(
            "gamdl",
            "--output-path", task_output_dir,
            *tracks_to_download,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
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
            downloaded_files = glob.glob(f"{task_output_dir}/**/*.m4a*", recursive=True)
            for file_path in downloaded_files:
                if file_path not in already_processed:
                    already_processed.add(file_path)
                    
                    # Check limit before processing
                    async with async_session() as session:
                        result = await session.exec(select(User).where(User.user_id == user_id_local))
                        user = result.one()
                        
                        if not user.is_premium and user.downloaded_today >= user.daily_limit:
                            await msg.answer("❌ Quota exhausted! Stopping further downloads.")
                            process.terminate()
                            return

                        # Extract metadata and upload
                        track_title, artist, thumbnail, duration = utils.extract_track_metadata(file_path)
                        abs_path = os.path.abspath(file_path)
                        
                        sent_msg = await msg.answer_audio(
                            audio=FSInputFile(abs_path),
                            title=track_title,
                            thumbnail=thumbnail,
                            performer=artist,
                            duration=duration
                        )

                        if sent_msg:
                            if not user.is_premium:
                                user.downloaded_today += 1
                                session.add(user)
                                await session.commit()

                            # Save to cache
                            tbot = Schema.TrackInputSchema(
                                file_id=sent_msg.audio.file_id,
                                file_unique_id=sent_msg.audio.file_unique_id,
                                title=track_title,
                                size=sent_msg.audio.file_size
                            )
                            
                            for original_track in songs:
                                if utils.convert_text(original_track.title) == utils.convert_text(tbot.title):
                                    track_input = Schema.TrackInputSchema(**original_track.model_dump())
                                    track_input.file_id = tbot.file_id
                                    track_input.file_unique_id = tbot.file_unique_id
                                    track_input.size = tbot.size
                                    await crud.save_single_track(session=session, track_data=track_input)
                                    await session.commit()
                                    break
                        
                        try:
                            os.remove(file_path)
                            print(f"Deleted local file: {file_path}")
                        except Exception as e:
                            print(f"Failed to delete {file_path}: {e}")

            await asyncio.sleep(1) # Small delay between checks

        return_code = await process.wait()
        if return_code == 0:
            await status_msg.edit_text("✅ All tracks processed successfully.")
        else:
            await status_msg.edit_text("⚠ Some tracks might have failed to download.")

    except Exception as e:
        print(f"Error handling download: {e}")
        await msg.answer("⚠️ An unexpected error occurred.")
    finally:
        if os.path.exists(task_output_dir):
            shutil.rmtree(task_output_dir)


async def worker() -> None:
    """
    Worker function to process the download queue.
    """
    while True:
        task = await download_queue.get()
        user_id = task["user_id"]

        user_lock = user_locks.setdefault(user_id, asyncio.Lock())

        async with user_lock:
            try:
                await process_download(task)
            except Exception as e:
                print(f"Worker caught execution exception: {e}")
            finally:
                download_queue.task_done()
        if download_queue.empty() and not user_lock.locked():
            user_in_queue.discard(user_id)

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

    # Start 3 concurrent workers
    for _ in range(3):
        asyncio.create_task(worker())

    print("Bot is starting...")
    await dp.start_polling(bot)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())