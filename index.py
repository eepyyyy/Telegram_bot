from datetime import date
from typing import List

from Crypto.Util.number import size
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile
from aiogram.filters import CommandStart
from aiogram.utils.markdown import hbold, hunderline, hcode
from aiogram.utils.keyboard import InlineKeyboardBuilder

import Schema
import asyncio
import crud
import glob
import os
import re
import shutil
import utils
import database
from database import get_session_maker, User
from gamdlUrl import get_any_url
from token_tl import TOKEN_API
from aiogram import types
from sqlmodel import Session, select

dp = Dispatcher()

async_session = get_session_maker()

download_queue: asyncio.Queue = asyncio.Queue()
user_in_queue: set[int] = set()

@dp.message(CommandStart())
async def cmd_start(msg: types.Message) -> None:
    """Renders the elegant main landing dashboard for the bot."""

    # Clean, sectioned typography for maximum readability
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
        f"• {hbold('Premium tier:')} Unlimited requests, full master-codec suite (ALAC/Atmos),videos coming soon, and priority processing queues.\n\n"

        f"💡 {hunderline('SHORTCUTS')}\n"
        f"Trigger instant search across any conversation window by typing: @applemusicdw_bot\n\n"
        f"Explore full features via /help • Check network regions via /countries"
    )

    # Modern, balanced grid layout for navigation buttons
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="💎 Upgrade to Premium", callback_data="menu_premium"),
    )
    builder.row(
        types.InlineKeyboardButton(text="🌍 Region Status", callback_data="menu_regions"),
        types.InlineKeyboardButton(text="📖 Guide / FAQ", callback_data="menu_faq")
    )
    builder.row(
        types.InlineKeyboardButton(text="🔍 Inline Search", switch_inline_query_current_chat="")
    )

    await msg.answer(
        text=welcome_text,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    print(msg.from_user.id)

@dp.message()
async def download_handle(msg: types.Message) -> None:
    user_id_local = msg.from_user.id

    if user_id_local in user_in_queue:
        await msg.answer("⏳ You already have a download in progress. Send more links once it's done.")
        return
    user_in_queue.add(user_id_local)
    position = download_queue.qsize()
    await msg.answer(f"✅ Queued (position {position + 1}).")
    await download_queue.put(msg)



async def process_download(msg: types.Message) -> None:
    message = msg.text
    user_id_local = msg.from_user.id

    status = await msg.answer('Downloading.....')
    unique_task_id = str(msg.message_id)
    task_output_dir = os.path.join("./downloads", unique_task_id)

    try:
        songs = await get_any_url(message)
        print(songs)

        file_ids, tracks_to_download = await crud.check_db_for_urls(songs)

        urls: List[str] = tracks_to_download
        async with async_session() as session:
            statement = select(User).where(User.user_id == user_id_local)
            result = await session.exec(statement)
            user = result.first()

            if not user:
                user = User(user_id = user_id_local)
                session.add(user)
                await session.commit()
                await session.refresh(user)

            if not user.is_premium:
                if user.last_download != date.today():
                    user.downloaded_today = 0
                    user.last_download = date.today()
                    session.add(user)
                    await session.commit()
                if user.downloaded_today >= user.daily_limit:
                    await msg.answer(
                        text="❌ You have reached your daily limit of 30 downloads! Support us on Ko-fi to unlock unlimited tier.")
                    return
            #     Acutal Upload loop
            for file in file_ids:
                if not user.is_premium and user.downloaded_today >= user.daily_limit:
                    await msg.answer("❌ Quota exhausted mid-delivery! Remaining tracks cancelled.")
                    return

                sent_db_msg = await msg.answer_audio(audio=file)
                if sent_db_msg and not user.is_premium:
                    user.downloaded_today += 1
                    session.add(user)
                    await session.commit()
            if not tracks_to_download:
                await msg.answer("✅ All tracks loaded from cache!")
                return


        process = await asyncio.create_subprocess_exec(
            "gamdl",
            "--output-path",
            task_output_dir,
            *urls,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            )

        ansi_escapes = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        already_downloaded = set()

        while True:
            line_bytes = await process.stdout.readline()

            if not line_bytes:
                break

            line = ansi_escapes.sub("", line_bytes.decode("utf-8", errors="ignore")).strip()
            print(line)

            downloaded_files = glob.glob(f"{task_output_dir}/**/*.m4a*", recursive=True)

            await asyncio.sleep(0.5)
            for upload in downloaded_files:
                if upload not in already_downloaded:
                    already_downloaded.add(upload)
                    print(upload)

                    abs_upload_path = os.path.abspath(upload)
                    # upload file and check db
                    track_title, artist, thumbnail, duration = utils.extract_track_metadata(upload)
                    if not user.is_premium and user.downloaded_today >= user.daily_limit:
                        await msg.answer("❌ Quota exhausted mid-delivery! Remaining tracks cancelled.")
                        process.terminate()
                        return

                    sent_msg = await msg.answer_audio(
                        audio=FSInputFile(abs_upload_path),
                        title=track_title,
                        thumbnail=thumbnail,
                        performer=artist,
                        duration=duration
                    )

                    if sent_msg and not user.is_premium:
                        async with async_session() as update_session:
                            user.downloaded_today += 1
                            update_session.add(user)
                            await update_session.commit()


                    tbot = Schema.TrackInputSchema(
                        file_id=sent_msg.audio.file_id,
                        file_unique_id=sent_msg.audio.file_unique_id,
                        title=track_title,
                        size=sent_msg.audio.file_size
                    )
                    print(tbot)
                    async with async_session() as session:
                        for track in songs:
                            print(track)
                            if utils.convert_text(track.title) == utils.convert_text(tbot.title):
                                print(track)
                                track_input = Schema.TrackInputSchema(**track.model_dump())
                                track_input.file_id = tbot.file_id
                                track_input.file_unique_id = tbot.file_unique_id
                                track_input.size = tbot.size
                                await crud.save_single_track(session=session, track_lists=track_input)
                                print(f"Saved to DB: {track_input.title}")
                                break
                    try:
                        os.remove(upload)
                        print(f"Deleted local file: {upload}")
                    except Exception as df_err:
                        print(f"Couldn't delete file: {upload}: {df_err}")


        return_code = await process.wait()
        if return_code == 0:
            await status.answer("✅ Download finished")
        else:
            await status.answer("❌ Download failed")


    except Exception as e:
        print(f"Error handling download: {e}")
        await msg.answer("⚠️ An unexpected error occurred while processing your request.")
    finally:
        if os.path.exists(task_output_dir):
            shutil.rmtree(task_output_dir)
            print(f"cleaned up temp directory: {task_output_dir}")


async def worker() -> None:
    while True:
        msg = await download_queue.get()
        try:
            await process_download(msg)
        finally:
            user_in_queue.discard(msg.from_user.id)
            download_queue.task_done()


async def main()-> None:
    """Entry Point"""

    bot = Bot(
        token=TOKEN_API,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )

    for _ in range(3):
        asyncio.create_task(worker())

    await dp.start_polling(bot)
    # Change "localhost" to your docker container_name

    # 1. Initialize local server
    # try:
    #     local_server = TelegramAPIServer.from_base("http://127.0.0.1:8081", is_local=True)
    #
    # # 2. Attach to a session
    #      = AiohttpSession(api=local_server)
    #
    #     bot = Bot(
    #         token=TOKEN_API,
    #         session=session,  # <--
    #         default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    #     )
    #     print("connecting to local server")
    # except Exception as e:
    #     print(f"local server failed ({e}) falling back to cloud")
    #
    #     bot = Bot(
    #         token=TOKEN_API,
    #         default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    #     )
    #
    # try:
    #     await dp.start_polling(bot)
    # except Exception as e:
    #     print(f"Polling failed {e}")


if __name__ == '__main__':
    asyncio.run(main())