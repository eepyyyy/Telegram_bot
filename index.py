from typing import List
from aiogram import Bot, Dispatcher, types
from debugpy.common.stacks import dump_after

from gamdlUrl import get_any_url
from database import get_session_maker
from aiogram.types import FSInputFile
from aiogram.filters import CommandStart
from aiogram.utils.markdown import hbold
import crud, utils, asyncio, os, re, glob, Schema, shutil
from token_tl import TOKEN_API

from aiogram.client.telegram import TelegramAPIServer
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

dp = Dispatcher()

async_session = get_session_maker()

@dp.message(CommandStart())
async def cmd_start(msg: types.Message) -> None:
    """Process the command 'start'"""
    text_md = f"hello, {hbold(msg.from_user.first_name)}"
    print(msg.chat.id)
    await msg.answer(
        text=text_md
    )

@dp.message()
async def handle_download(msg: types.Message) -> None:
    message = msg.text

    status = await msg.answer('Downloading.....')
    unique_task_id = str(msg.message_id)
    task_output_dir = os.path.join("./downloads", unique_task_id)

    try:
        songs = await get_any_url(message)

        file_ids, tracks_to_download = await crud.check_db_for_urls(songs)

        for file in file_ids:
            await msg.answer_audio(audio=file)

        if not tracks_to_download:
            await msg.answer("✅ All tracks loaded from cache!")
            return

        urls: List[str] = tracks_to_download

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
                    # upload file
                    track_title, artist, thumbnail, duration = utils.extract_track_metadata(upload)

                    sent_msg = await msg.answer_audio(
                        audio=FSInputFile(abs_upload_path),
                        title=track_title,
                        thumbnail=thumbnail,
                        performer=artist,
                        duration=duration
                    )

                    tbot = Schema.TrackInputSchema(
                        file_id=sent_msg.audio.file_id,
                        file_unique_id=sent_msg.audio.file_unique_id,
                        title=track_title
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
        print(f"An error occurred: {e}")
        await status.edit_text("An unexpected error occurred.")
    finally:
        if os.path.exists(task_output_dir):
            shutil.rmtree(task_output_dir)
            print(f"cleaned up temp directory: {task_output_dir}")

async def main()-> None:
    """Entry Point"""

    bot = Bot(
        token=TOKEN_API,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
    await dp.start_polling(bot)
    # Change "localhost" to your docker container_name

    # 1. Initialize local server
    # try:
    #     local_server = TelegramAPIServer.from_base("http://127.0.0.1:8081", is_local=True)
    #
    # # 2. Attach to a session
    #     session = AiohttpSession(api=local_server)
    #
    #     bot = Bot(
    #         token=TOKEN_API,
    #         session=session,  # <--
    #         default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    #     )
    #     print("connecting to local server")
    # except Exception as e:
    #     print(f"local server failed ({e}) falling back to to cloud")
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