from aiogram import Bot, Dispatcher, types
from aiogram.types import FSInputFile
from token_tl import TOKEN_API
from aiogram.filters import CommandStart
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from database import get_session_maker
import database
import asyncio
import os
from gamdlUrl import get_album_urls, get_any_url, get_playlist_urls
import re
import glob
from aiogram.utils.markdown import hbold
import Schema
from crud import save_track_to_bot_db, check_db_for_urls


dp = Dispatcher()

async_session = get_session_maker()

@dp.message(CommandStart())
async def cmd_start(msg: types.Message) -> None:
    """Process the commond 'start'"""
    text_md = F"helloe, {hbold(msg.from_user.first_name)}"
    print(msg.chat.id)
    await msg.answer(
        text=text_md
    )

@dp.message()
async def cmd_start(msg: types.Message) -> None:
    message = msg.text

    status = await msg.answer('Donwloading.....')
    unique_task_id = str(msg.message_id)
    task_output_dir = os.path.join("./downloads", unique_task_id)

    songs = await get_any_url(message)

    urls = [song.url for song in songs]

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
        
        line = ansi_escapes.sub("", line_bytes.decode("utf-8", errors="ignore")
        ).strip()
        print(line)

        downloaded_files = glob.glob(f"{task_output_dir}/**/*.m4a*", recursive=True)
        async with async_session() as session:
            for upload in downloaded_files:
                if upload not in already_downloaded:
                    sent_msg = await msg.answer_audio(audio=FSInputFile(upload), caption="test")
                    tbot = Schema.TrackInputSchema(
                        file_id=sent_msg.audio.file_id,
                        unique_file_id=sent_msg.audio.file_unique_id,
                        title=sent_msg.audio.file_name.removesuffix(".m4a").strip().removesuffix(".m4a")
                    )

                    print(tbot)
                    for track in songs:
                        track_input = Schema.TrackInputSchema(**track.model_dump())
                        if track_input.title == tbot.title:
                            track_input.file_id = tbot.file_id
                            track_input.file_unique_id = tbot.file_unique_id
                            db_update = database.Tracks(track_input)
                            session.add(db_update)

                            await session.commit()
                            print(track)
                            break
                    already_downloaded.add(upload)


    return_code = await process.wait()


    if return_code == 0:
        await status.edit_text("✅ Download finished")
    else:
        await status.edit_text("❌ Download failed") 

async def main()-> None:
    """Entry Point"""

    bot = Bot(
        token=TOKEN_API,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())