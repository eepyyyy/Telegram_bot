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
import time
from queues import aac_queue, aac_in_queue, aac_pending_jobs, aac_locks, is_user_busy, active_tasks

aac = Router()

@aac.message(Command("aac"))
async def aac_download(msg: types.Message, command: CommandObject) -> None:
    url = (command.args or "").strip()

    if not re.fullmatch(r"https?://\S+", url):
        try:
            await msg.answer("Usage:\n/aac &lt;Apple Music URL&gt;")
        except Exception:
            pass
        return

    user_id_local = msg.from_user.id
    if is_user_busy(user_id_local):
        try:
            await msg.answer("⏳ You already have a download in progress. Please wait until it's finished.")
        except Exception:
            pass
        return

    # Mark user busy immediately
    aac_in_queue.add(user_id_local)

    # Fetch metadata to see how many tracks
    status_msg = await msg.answer("🔍 Fetching AAC metadata...")
    try:
        songs = await get_any_url(url)
    except Exception as e:
        aac_in_queue.discard(user_id_local)
        try:
            await status_msg.edit_text(f"❌ Failed to fetch metadata: {str(e)}")
        except Exception:
            pass
        return

    if not songs:
        aac_in_queue.discard(user_id_local)
        try:
            await status_msg.edit_text("❌ No tracks found.")
        except Exception:
            pass
        return

    # Check database for existing AAC cached tracks
    file_ids, tracks_to_download = await crud.check_db_for_urls(songs, format_type="aac")

    for file_id in file_ids:
        try:
            sent_msg = await msg.answer_audio(audio=file_id)
        except Exception:
            sent_msg = None
        if sent_msg:
            async with async_session() as session:
                result = await session.exec(select(User).where(User.user_id == user_id_local))
                user = result.first()
                if user:
                    user.download_count += 1
                    session.add(user)
                    await session.commit()
                    
                    # Log cached delivery
                    try:
                        db_track = (await session.exec(select(database.AACTracks).where(database.AACTracks.file_id == file_id))).first()
                        song_id_val = db_track.song_id if db_track else None
                        size_val = db_track.size if db_track else 0
                        await crud.log_download(
                            session=session,
                            user_id=user_id_local,
                            song_id=song_id_val,
                            format_type="aac",
                            size=size_val,
                            is_cached=True
                        )
                        await session.commit()
                    except Exception as le:
                        print(f"Failed to log cached AAC download: {le}")

    if not tracks_to_download:
        aac_in_queue.discard(user_id_local)
        try:
            await status_msg.edit_text("✅ All AAC tracks delivered from cache!")
        except Exception:
            pass
        return

    # Queue the missing tracks
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

    track_title = "AAC Track"
    artist = "Unknown Artist"
    if songs:
        track_title = songs[0].title
        artist = songs[0].artist
        if len(songs) > 1:
            track_title = songs[0].album or f"{songs[0].title} (+{len(songs)-1} tracks)"

    active_tasks[unique_task_id] = {
        "process": None,
        "cancelled": False,
        "user_id": user_id_local,
        "status_msg": status_msg,
        "track_title": track_title,
        "artist": artist,
        "format": "AAC",
        "status": "downloading",
        "start_time": time.time(),
        "progress": 0,
    }

    temp_dir = f"{output_dir}_temp"
    try:
        await asyncio.to_thread(os.makedirs, output_dir, exist_ok=True)
        await asyncio.to_thread(os.makedirs, temp_dir, exist_ok=True)

        # Start downloading
        cookies_path = os.path.abspath("cookies.txt")
        cookies_args = ["--cookies-path", cookies_path] if os.path.exists(cookies_path) else []

        process = await asyncio.create_subprocess_exec(
            "gamdl",
            "-n",
            *cookies_args,
            "--truncate", "80",
            "--output-path", output_dir,
            "--temp-path", temp_dir,
            "--song-codec-priority", "aac-web",
            track_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            limit=10 * 1024 * 1024,
        )
        if unique_task_id in active_tasks:
            active_tasks[unique_task_id]["process"] = process

        ansi_escapes = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        uploaded_files = set()

        while True:
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
                print(f"[gamdl AAC] {line}")
                if "Requested format is not available" in line:
                    try:
                        process.terminate()
                        await process.wait()
                    except ProcessLookupError:
                        pass
                    try:
                        await status_msg.edit_text(
                            "⚠️ <b>AAC format is not available</b> for this track/album.",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
                    return

            # Check for new finalized files
            downloaded_files = await asyncio.to_thread(
                glob.glob, os.path.join(output_dir, "**", "*.m4a"), recursive=True
            )
            for file_path in downloaded_files:
                norm_p = file_path.replace("\\", "/")
                filename = os.path.basename(norm_p)
                if "gamdl_temp" in norm_p or "_temp" in norm_p or filename.endswith("_encrypted.m4a") or filename.endswith(".tmp"):
                    continue

                if file_path not in uploaded_files:
                    uploaded_files.add(file_path)

                    # Fetch user before uploading
                    async with async_session() as session:
                        result = await session.exec(select(User).where(User.user_id == user_id_local))
                        user = result.one()

                        # Extract metadata
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
                            user.download_count += 1
                            session.add(user)
                            await session.commit()

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
                            if isrc:
                                for original_track in songs:
                                    if original_track.isrc == isrc:
                                        track_input = schema.TrackInputSchema(**original_track.model_dump())
                                        track_input.file_id = tbot.file_id
                                        track_input.file_unique_id = tbot.file_unique_id
                                        track_input.size = tbot.size
                                        track_input.chat_id = tbot.chat_id
                                        track_input.message_id = tbot.message_id
                                        await crud.save_single_track(session=session, track_data=track_input, format_type="aac")
                                        await session.commit()
                                        
                                        # Log download history
                                        try:
                                            await crud.log_download(
                                                session=session,
                                                user_id=user_id_local,
                                                song_id=track_input.song_id,
                                                format_type="aac",
                                                size=tbot.size,
                                                is_cached=False
                                            )
                                            await session.commit()
                                        except Exception as le:
                                            print(f"Failed to log AAC download history: {le}")
                                            
                                        matched = True
                                        break

                            if not matched:
                                for original_track in songs:
                                    if utils.convert_text(original_track.title) == utils.convert_text(tbot.title):
                                        track_input = schema.TrackInputSchema(**original_track.model_dump())
                                        track_input.file_id = tbot.file_id
                                        track_input.file_unique_id = tbot.file_unique_id
                                        track_input.size = tbot.size
                                        track_input.chat_id = tbot.chat_id
                                        track_input.message_id = tbot.message_id
                                        await crud.save_single_track(session=session, track_data=track_input, format_type="aac")
                                        await session.commit()
                                        
                                        # Log download history
                                        try:
                                            await crud.log_download(
                                                session=session,
                                                user_id=user_id_local,
                                                song_id=track_input.song_id,
                                                format_type="aac",
                                                size=tbot.size,
                                                is_cached=False
                                            )
                                            await session.commit()
                                        except Exception as le:
                                            print(f"Failed to log AAC download history: {le}")
                                            
                                        break

                        try:
                            await asyncio.to_thread(os.remove, file_path)
                        except Exception as e:
                            print(f"Failed to remove file {file_path}: {e}")

            await asyncio.sleep(1)

        return_code = await process.wait()
        if return_code == 0:
            try:
                await status_msg.edit_text("✅ AAC download and upload completed.\n\n🌐 Link can be downloaded at: https://stream.eepy.in/")
            except Exception:
                pass
        else:
            try:
                await status_msg.edit_text("⚠ AAC download finished with errors.\n\n🌐 Link can be downloaded at: https://stream.eepy.in/")
            except Exception:
                pass

    except Exception as error:
        print(f"AAC download error: {error}")
        try:
            await status_msg.edit_text(f"AAC download failed: {error}")
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

        for d_clean in (output_dir, temp_dir):
            if await asyncio.to_thread(os.path.exists, d_clean):
                try:
                    await asyncio.to_thread(shutil.rmtree, d_clean)
                except Exception as e:
                    print(f"Failed to delete {d_clean}: {e}")


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
            try:
                await process_aac_download(task)
            except Exception as e:
                print(f"AAC worker caught execution exception: {e}")
            finally:
                remaining = aac_pending_jobs.get(user_id, 1) - 1
                if remaining <= 0:
                    aac_pending_jobs.pop(user_id, None)
                    aac_in_queue.discard(user_id)
                    aac_locks.pop(user_id, None)
                else:
                    aac_pending_jobs[user_id] = remaining
                aac_queue.task_done()