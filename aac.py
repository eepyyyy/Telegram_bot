import asyncio
import glob
import os
import re
import shutil
from datetime import datetime, timezone

from aiogram import Router, types
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, FSInputFile
from sqlmodel import select

import utils
import schema
import crud
import database
from database import User, async_session
from gamdlUrl import get_any_url
from queues import aac_queue, aac_in_queue, aac_pending_jobs, aac_locks

aac = Router()

@aac.message(Command("aac"))
async def aac_download(msg: types.Message, command: CommandObject) -> None:
    url = (command.args or "").strip()

    if not re.fullmatch(r"https?://\S+", url):
        try:
            await msg.answer("Usage:\n/aac <Apple Music URL>")
        except Exception:
            pass
        return

    user_id_local = msg.from_user.id
    if user_id_local in aac_in_queue:
        try:
            await msg.answer("⏳ You already have an AAC download in progress. Please wait.")
        except Exception:
            pass
        return

    # Check database daily limit before enqueuing
    async with async_session() as session:
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

        if not user.is_premium and user.downloaded_today >= user.daily_limit:
            try:
                await msg.answer("❌ Daily download limit reached.")
            except Exception:
                pass
            return

    # Fetch metadata to see how many tracks
    status_msg = await msg.answer("🔍 Fetching AAC metadata...")
    try:
        songs = await get_any_url(url)
    except Exception as e:
        try:
            await status_msg.edit_text(f"❌ Failed to fetch metadata: {str(e)}")
        except Exception:
            pass
        return

    if not songs:
        try:
            await status_msg.edit_text("❌ No tracks found.")
        except Exception:
            pass
        return

    # Check cache first for files!
    file_ids, tracks_to_download = await crud.check_db_for_urls(songs)

    # Deliver cached files immediately!
    async with async_session() as session:
        result = await session.exec(select(User).where(User.user_id == user_id_local))
        user = result.one()
        for file_id in file_ids:
            try:
                await msg.answer_audio(audio=file_id)
            except Exception:
                pass
            user.download_count += 1
            session.add(user)
            await session.commit()

    if not tracks_to_download:
        try:
            await status_msg.edit_text("✅ All tracks delivered from cache!")
        except Exception:
            pass
        return

    # Queue the missing tracks
    aac_in_queue.add(user_id_local)
    aac_pending_jobs[user_id_local] = len(tracks_to_download)
    position = aac_queue.qsize()
    
    try:
        await status_msg.edit_text(f"Queued {len(tracks_to_download)} AAC track(s) (starting at position {position + 1}).")
    except Exception:
        pass

    for track_url in tracks_to_download:
        await aac_queue.put({
            "url": track_url,
            "songs": songs,
            "msg": msg,
            "user_id": user_id_local,
            "status_msg": status_msg
        })


async def process_aac_download(task: dict) -> None:
    track_url = task["url"]
    songs = task["songs"]
    msg: Message = task["msg"]
    user_id_local = task["user_id"]
    status_msg = task["status_msg"]

    unique_task_id = f"aac_{msg.message_id}_{int(asyncio.get_event_loop().time() * 1000)}"
    output_dir = os.path.abspath(os.path.join("downloads", unique_task_id))
    process = None

    try:
        await asyncio.to_thread(os.makedirs, output_dir, exist_ok=True)

        # Start downloading
        process = await asyncio.create_subprocess_exec(
            "gamdl",
            "-n",
            "--output-path", output_dir,
            "--song-codec-priority", "aac-web",
            track_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        ansi_escapes = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        uploaded_files = set()

        while True:
            line_bytes = await process.stdout.readline()
            if not line_bytes:
                break

            line = ansi_escapes.sub("", line_bytes.decode("utf-8", errors="ignore")).strip()
            if line:
                print(f"[gamdl AAC] {line}")

            # Check for new files
            downloaded_files = await asyncio.to_thread(
                glob.glob, os.path.join(output_dir, "**", "*.m4a*"), recursive=True
            )
            for file_path in downloaded_files:
                if file_path not in uploaded_files:
                    uploaded_files.add(file_path)

                    # Check limit before uploading
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

                        # Extract metadata
                        track_title, artist, thumbnail, duration, isrc = await asyncio.to_thread(
                            utils.extract_track_metadata, file_path
                        )

                        try:
                            sent_msg = await msg.answer_audio(
                                audio=FSInputFile(file_path),
                                title=track_title,
                                performer=artist,
                                thumbnail=thumbnail,
                                duration=duration,
                            )
                        except Exception as e:
                            print(f"Failed to send AAC audio message: {e}")
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
                        except Exception as e:
                            print(f"Failed to remove file {file_path}: {e}")

            await asyncio.sleep(1)

        return_code = await process.wait()
        if return_code == 0:
            try:
                await status_msg.edit_text("✅ AAC download and upload completed.")
            except Exception:
                pass
        else:
            try:
                await status_msg.edit_text("⚠️ AAC download finished with errors. Check logs.")
            except Exception:
                pass

    except Exception as error:
        print(f"AAC download error: {error}")
        try:
            await status_msg.edit_text(f"❌ AAC download failed: {error}")
        except Exception:
            pass
    finally:
        if process and process.returncode is None:
            try:
                process.terminate()
                await process.wait()
            except ProcessLookupError:
                pass

        if await asyncio.to_thread(os.path.exists, output_dir):
            try:
                await asyncio.to_thread(shutil.rmtree, output_dir)
            except Exception as e:
                print(f"Failed to delete {output_dir}: {e}")


async def aac_worker() -> None:
    """
    Worker function to process the aac download queue. Up to 10 run concurrently.
    """
    while True:
        task = await aac_queue.get()
        user_id = task["user_id"]
        msg = task["msg"]

        user_lock = aac_locks.setdefault(user_id, asyncio.Lock())

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
                            await msg.answer("❌ Daily download limit reached. Skipping AAC queued item.")
                        except Exception:
                            pass
                        aac_queue.task_done()
                        remaining = aac_pending_jobs.get(user_id, 1) - 1
                        if remaining <= 0:
                            aac_pending_jobs.pop(user_id, None)
                            aac_in_queue.discard(user_id)
                            aac_locks.pop(user_id, None)
                        else:
                            aac_pending_jobs[user_id] = remaining
                        continue

            try:
                await process_aac_download(task)
            except Exception as e:
                print(f"AAC worker caught execution exception: {e}")
            finally:
                aac_queue.task_done()

        remaining = aac_pending_jobs.get(user_id, 1) - 1
        if remaining <= 0:
            aac_pending_jobs.pop(user_id, None)
            aac_in_queue.discard(user_id)
            aac_locks.pop(user_id, None)
        else:
            aac_pending_jobs[user_id] = remaining