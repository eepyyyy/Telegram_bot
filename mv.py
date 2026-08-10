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
from queues import mv_queue, mv_in_queue, mv_pending_jobs, mv_locks, is_user_busy

mv = Router()


@mv.message(Command("mv"))
async def mv_download(msg: types.Message, command: CommandObject) -> None:
    """
    Command handler for downloading Apple Music Music Videos.
    Usage:
      /mv <Apple Music Video URL>
      /mv h265 <Apple Music Video URL>
      /mv h264 <Apple Music Video URL>
    """
    raw_args = (command.args or "").strip()
    parts = raw_args.split(maxsplit=1)

    codec = None
    url = ""

    if len(parts) == 2 and parts[0].lower() in ("h265", "hevc", "h264"):
        codec = parts[0].lower()
        if codec == "hevc":
            codec = "h265"
        url = parts[1].strip()
    elif len(parts) >= 1:
        url = parts[0].strip()

    if not re.fullmatch(r"https?://\S+", url):
        try:
            await msg.answer(
                "<b>Usage:</b>\n"
                "• <code>/mv &lt;Apple Music Video URL&gt;</code> (Auto best format)\n"
                "• <code>/mv h265 &lt;Apple Music Video URL&gt;</code> (Force H.265/HEVC)\n"
                "• <code>/mv h264 &lt;Apple Music Video URL&gt;</code> (Force H.264)",
                parse_mode="HTML"
            )
        except Exception:
            pass
        return

    await process_mv_enqueue(msg, url, codec=codec)


async def process_mv_enqueue(msg: types.Message, url: str, codec: str | None = None) -> None:
    """
    Validates limits, checks cache, and queues Music Video download tasks.
    """
    user_id_local = msg.from_user.id
    if is_user_busy(user_id_local):
        try:
            await msg.answer("⏳ You already have a download in progress. Please wait until it's finished.")
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

    status_msg = await msg.answer("🔍 Fetching Music Video metadata...")
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
            await status_msg.edit_text("❌ No music video content found.")
        except Exception:
            pass
        return

    # Check database for existing MV cached tracks
    file_ids, tracks_to_download = await crud.check_db_for_urls(songs, format_type="mv")

    for file_id in file_ids:
        try:
            sent_msg = await msg.answer_video(video=file_id)
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

    if not tracks_to_download:
        try:
            await status_msg.edit_text("✅ Music Video delivered from cache!\n\n🌐 Streaming Link: https://stream.eepy.in/")
        except Exception:
            pass
        return

    # Queue the missing video tracks
    mv_in_queue.add(user_id_local)
    mv_pending_jobs[user_id_local] = len(tracks_to_download)
    position = mv_queue.qsize()

    try:
        codec_str = f" ({codec.upper()})" if codec else ""
        await status_msg.edit_text(f"🎬 Queued Music Video{codec_str} at position #{position + 1}. Download starting...")
    except Exception:
        pass

    for track_url in tracks_to_download:
        await mv_queue.put({
            "url": track_url,
            "songs": songs,
            "msg": msg,
            "user_id": user_id_local,
            "status_msg": status_msg,
            "codec": codec
        })


async def run_gamdl_mv_subprocess(output_dir: str, temp_dir: str, track_url: str, codec: str | None = None) -> tuple[int, bool]:
    """
    Executes gamdl for Music Video. If codec is None, leaves command empty for native gamdl codec selection.
    Returns (return_code, format_unavailable).
    """
    cmd = [
        "gamdl",
        "-n",
        "--output-path", output_dir,
        "--temp-path", temp_dir,
    ]
    if codec:
        cmd.extend(["--music-video-codec-priority", codec])
    cmd.append(track_url)

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        limit=10 * 1024 * 1024,
    )

    ansi_escapes = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    format_unavailable = False

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
            print(f"[gamdl MV] {line}")
            if "Requested format is not available" in line:
                format_unavailable = True

    return_code = await process.wait()
    return return_code, format_unavailable


async def process_mv_download(task: dict) -> None:
    """
    Executes gamdl for Music Videos using native gamdl format selection (or requested codec).
    """
    track_url = task["url"]
    songs = task["songs"]
    msg: Message = task["msg"]
    user_id_local = task["user_id"]
    status_msg = task["status_msg"]
    requested_codec = task.get("codec")

    unique_task_id = f"mv_{msg.message_id}_{int(asyncio.get_event_loop().time() * 1000)}"
    output_dir = os.path.abspath(os.path.join("downloads", unique_task_id))
    temp_dir = f"{output_dir}_temp"

    try:
        await asyncio.to_thread(os.makedirs, output_dir, exist_ok=True)
        await asyncio.to_thread(os.makedirs, temp_dir, exist_ok=True)

        try:
            await status_msg.edit_text("🎬 Downloading Music Video...")
        except Exception:
            pass

        return_code, format_unavailable = await run_gamdl_mv_subprocess(output_dir, temp_dir, track_url, requested_codec)

        # Check for downloaded video files
        downloaded_files = []
        for ext in ("*.m4v", "*.mp4", "*.mkv"):
            found = await asyncio.to_thread(
                glob.glob, os.path.join(output_dir, "**", ext), recursive=True
            )
            downloaded_files.extend(found)

        valid_files = [
            f for f in downloaded_files
            if not ("gamdl_temp" in f.replace("\\", "/") or "_temp" in f.replace("\\", "/") or f.endswith(".tmp"))
        ]

        if valid_files and not format_unavailable:
            for file_path in valid_files:
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
                            await msg.answer("Quota exhausted! Halting further downloads.")
                        except Exception:
                            pass
                        return

                    # Extract video metadata
                    track_title, artist, thumbnail, duration, isrc = await asyncio.to_thread(
                        utils.extract_track_metadata, file_path
                    )

                    # Deliver video file via Telegram (upload to channel and deliver to user)
                    try:
                        caption = f"🎬 <b>{track_title}</b>\n👤 {artist}"
                        sent_msg, saved_chat_id, saved_message_id = await utils.upload_and_deliver_video(
                            bot=msg.bot,
                            user_chat_id=msg.chat.id,
                            file_path=file_path,
                            caption=caption,
                            thumbnail=thumbnail,
                            duration=duration
                        )
                    except Exception as e:
                        print(f"Failed to upload video to Telegram: {e}")
                        sent_msg = None
                        saved_chat_id = msg.chat.id
                        saved_message_id = None

                    if sent_msg:
                        user.download_count += 1
                        if not user.is_premium:
                            user.downloaded_today += 1
                            session.add(user)
                            await session.commit()

                        media_obj = sent_msg.video or sent_msg.document
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
                                    await crud.save_single_track(session=session, track_data=track_input, format_type="mv")
                                    await session.commit()
                                    matched = True
                                    break

                        if not matched and songs:
                            track_input = schema.TrackInputSchema(**songs[0].model_dump())
                            track_input.file_id = tbot.file_id
                            track_input.file_unique_id = tbot.file_unique_id
                            track_input.size = tbot.size
                            track_input.chat_id = tbot.chat_id
                            track_input.message_id = tbot.message_id
                            await crud.save_single_track(session=session, track_data=track_input, format_type="mv")
                            await session.commit()

                    try:
                        await asyncio.to_thread(os.remove, file_path)
                    except Exception as e:
                        print(f"Failed to remove video file {file_path}: {e}")

            try:
                await status_msg.edit_text("✅ Music Video download and delivery completed!\n\n🌐 Streaming Link: https://stream.eepy.in/")
            except Exception:
                pass
        else:
            try:
                await status_msg.edit_text("⚠️ <b>Requested video format is not available</b> on Apple Music for this item.", parse_mode="HTML")
            except Exception:
                pass

    except Exception as error:
        print(f"Music Video download error: {error}")
        try:
            await status_msg.edit_text(f"Music Video download failed: {error}")
        except Exception:
            pass
    finally:
        for d_clean in (output_dir, temp_dir):
            if await asyncio.to_thread(os.path.exists, d_clean):
                try:
                    await asyncio.to_thread(shutil.rmtree, d_clean)
                except Exception as e:
                    print(f"Failed to delete {d_clean}: {e}")


async def mv_worker() -> None:
    """
    Worker function to process the Music Video download queue.
    """
    while True:
        task = await mv_queue.get()
        user_id = task["user_id"]

        user_lock = mv_locks.setdefault(user_id, asyncio.Lock())

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
                            msg = task["msg"]
                            await msg.answer("❌ Daily limit reached. Skipping queued Music Video.")
                        except Exception:
                            pass
                        remaining = mv_pending_jobs.get(user_id, 1) - 1
                        if remaining <= 0:
                            mv_pending_jobs.pop(user_id, None)
                            mv_in_queue.discard(user_id)
                            mv_locks.pop(user_id, None)
                        else:
                            mv_pending_jobs[user_id] = remaining
                        mv_queue.task_done()
                        continue

            try:
                await process_mv_download(task)
            except Exception as e:
                print(f"Error processing Music Video download: {e}")
            finally:
                remaining = mv_pending_jobs.get(user_id, 1) - 1
                if remaining <= 0:
                    mv_pending_jobs.pop(user_id, None)
                    mv_in_queue.discard(user_id)
                    mv_locks.pop(user_id, None)
                else:
                    mv_pending_jobs[user_id] = remaining
                mv_queue.task_done()
