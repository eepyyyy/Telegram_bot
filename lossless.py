import asyncio
import glob
import os
import re
import shutil
from datetime import datetime, timezone
from typing import Optional, List, Tuple

from aiogram import Router, types
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.markdown import hbold, hcode
from mutagen.mp4 import MP4
from sqlmodel import select

import crud
import database
import schema
import utils
from database import User, async_session
from gamdlUrl import get_any_url
from queues import (
    active_tasks,
    is_user_busy,
    lossless_in_queue,
    lossless_locks,
    lossless_pending_jobs,
    lossless_queue,
)

lossless = Router()


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


async def remux_to_48k_alac(file_path: str) -> bool:
    """
    Checks audio sample rate of an .m4a ALAC file.
    If sample_rate > 48000 Hz (Hi-Res), remuxes/resamples it to 48kHz ALAC using FFmpeg
    and copies all mutagen metadata/artwork from source to destination.
    
    Returns:
        True if the file was remuxed from Hi-Res to 48kHz.
        False if the file was already <= 48kHz and did not require remuxing.
    """
    try:
        def read_sample_rate():
            audio = MP4(file_path)
            return audio.info.sample_rate if audio.info else 44100

        sample_rate = await asyncio.to_thread(read_sample_rate)
    except Exception as e:
        print(f"[Lossless Remux] Failed to inspect audio sample rate for {file_path}: {e}")
        sample_rate = 44100

    if sample_rate <= 48000:
        # Already standard Lossless (16/44.1kHz or 24/48kHz)
        return False

    print(f"[Lossless Remux] Detected Hi-Res Lossless ({sample_rate}Hz) for {file_path}. Remuxing to 48kHz ALAC...")

    temp_output = f"{file_path}.48k.m4a"
    cmd = [
        "ffmpeg",
        "-y",
        "-i", file_path,
        "-map", "0:a:0",
        "-c:a", "alac",
        "-ar", "48000",
        temp_output
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            print(f"[Lossless Remux] FFmpeg exited with code {proc.returncode}: {stderr.decode('utf-8', errors='ignore')}")
            if os.path.exists(temp_output):
                try:
                    os.remove(temp_output)
                except Exception:
                    pass
            return False

        # Copy all tags and cover art from source to target
        def copy_tags():
            src_mp4 = MP4(file_path)
            dst_mp4 = MP4(temp_output)
            if src_mp4.tags:
                for k, v in src_mp4.tags.items():
                    dst_mp4.tags[k] = v
                dst_mp4.save()

        await asyncio.to_thread(copy_tags)

        # Replace original file with remuxed file
        await asyncio.to_thread(os.replace, temp_output, file_path)
        print(f"[Lossless Remux] Successfully remuxed {file_path} to 48kHz ALAC.")
        return True

    except Exception as e:
        print(f"[Lossless Remux] Exception while remuxing {file_path}: {e}")
        if os.path.exists(temp_output):
            try:
                os.remove(temp_output)
            except Exception:
                pass
        return False


@lossless.message(Command("lossless"))
async def lossless_download(msg: types.Message, command: CommandObject) -> None:
    """
    Handles /lossless command for downloading regular Lossless (up to 24-bit / 48kHz ALAC).
    Automatically downsamples Hi-Res tracks to 48kHz and avoids storing remuxed tracks in DB.
    """
    url = (command.args or "").strip()

    if not re.search(r"https?://\S+", url):
        usage_text = (
            "<b>Apple Music Regular Lossless Downloader</b>\n\n"
            "⚠️ <b>Deprecation Notice:</b> The <code>/lossless</code> command is deprecated. Please use normal download by sending the link directly to this chat instead.\n\n"
            "<b>Usage:</b>\n"
            "<code>/lossless &lt;Apple Music URL&gt;</code>\n\n"
            "• <b>Audio Quality:</b> ALAC Lossless (up to 24-bit / 48kHz)\n"
            "• <b>Hi-Res Handling:</b> Converts Hi-Res Lossless (96kHz/192kHz) to standard 48kHz Lossless automatically.\n"
            "• <b>Normal Download:</b> Send link directly to download in standard / Hi-Res Lossless."
        )
        try:
            await msg.answer(usage_text, parse_mode="HTML")
        except Exception:
            pass
        return

    user_id_local = msg.from_user.id
    if is_user_busy(user_id_local):
        try:
            await msg.answer("⏳ You already have an active download task in progress. Please wait until it completes.")
        except Exception:
            pass
        return

    # Mark user busy immediately
    lossless_in_queue.add(user_id_local)

    status_msg = await msg.answer("🔍 Fetching Lossless metadata...")

    try:
        songs = await get_any_url(url)
    except Exception as e:
        lossless_in_queue.discard(user_id_local)
        try:
            await status_msg.edit_text(f"❌ Failed to fetch metadata: {str(e)}")
        except Exception:
            pass
        return

    if not songs:
        lossless_in_queue.discard(user_id_local)
        try:
            await status_msg.edit_text("❌ No tracks found.")
        except Exception:
            pass
        return

    # Check if Lossless format is available in Apple Music metadata
    has_lossless = any(
        any(t in (s.audio_traits or []) for t in ("lossless", "hi-res-lossless"))
        for s in songs
    )
    if not has_lossless:
        lossless_in_queue.discard(user_id_local)
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

    # Check database cache for tracks that are strictly regular lossless (not hi-res)
    # If a track has hi-res-lossless in audio_traits, the cached file in DB might be Hi-Res,
    # so we require a fresh download and 48kHz remux instead of delivering from cache.
    cached_candidate_songs = [
        s for s in songs
        if not any(t == "hi-res-lossless" for t in (s.audio_traits or []))
    ]

    file_ids_cached = []
    if cached_candidate_songs:
        file_ids_cached, _ = await crud.check_db_for_urls(cached_candidate_songs, format_type="alac")

    total_tracks = len(songs)
    completed_count = 0

    # Deliver cached standard lossless tracks
    for file_id in file_ids_cached:
        try:
            sent_msg = await msg.answer_audio(audio=file_id)
        except Exception:
            sent_msg = None

        if sent_msg:
            completed_count += 1
            async with async_session() as session:
                result = await session.exec(select(User).where(User.user_id == user_id_local))
                user = result.first()
                if user:
                    user.download_count += 1
                    session.add(user)
                    await session.commit()

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
                        print(f"Failed to log cached Lossless download history: {le}")

    # Determine tracks still needing download
    cached_song_ids = set()
    if file_ids_cached:
        async with async_session() as session:
            stmt = select(database.Tracks.song_id, database.Tracks.file_id).where(database.Tracks.file_id.in_(file_ids_cached))
            rows = (await session.exec(stmt)).all()
            cached_song_ids = {r[0] for r in rows if r[0]}

    tracks_to_download = []
    for s in songs:
        if s.song_id and s.song_id in cached_song_ids:
            continue
        if s.url:
            tracks_to_download.append(str(s.url))

    if not tracks_to_download:
        lossless_in_queue.discard(user_id_local)
        try:
            await status_msg.edit_text(
                "✅ All regular Lossless tracks delivered from cache!\n\n"
                "⚠️ <b>Notice:</b> The <code>/lossless</code> command is deprecated. Please use normal download (send links directly) instead.\n\n"
                "🌐 Link can be downloaded at: https://stream.eepy.in/"
            )
        except Exception:
            pass
        return

    # Queue the missing tracks for download and 48kHz remux
    lossless_pending_jobs[user_id_local] = 1
    position = lossless_queue.qsize()

    try:
        await status_msg.edit_text(
            f"Queued regular Lossless download (position #{position + 1}). Live progress will update below:\n\n"
            f"⚠️ <i>Note: The <code>/lossless</code> command is deprecated. Please use normal download (send links directly) instead.</i>"
        )
    except Exception:
        pass

    await lossless_queue.put({
        "url": url,
        "tracks_to_download": tracks_to_download,
        "songs": songs,
        "msg": msg,
        "status_msg": status_msg,
        "user_id": user_id_local,
        "completed_count": completed_count,
        "total_tracks": total_tracks
    })


async def process_lossless_download(task: dict) -> None:
    """
    Downloads requested tracks using gamdl, verifies sample rate, remuxes Hi-Res tracks to 48kHz ALAC,
    delivers to user, and avoids storing remuxed tracks in database.
    """
    tracks_to_download: List[str] = task["tracks_to_download"]
    songs = task["songs"]
    msg: Message = task["msg"]
    status_msg: Message = task["status_msg"]
    user_id_local: int = task["user_id"]
    completed_count: int = task.get("completed_count", 0)
    total_tracks: int = task.get("total_tracks", len(songs))

    unique_task_id = f"lossless_{msg.message_id}_{int(asyncio.get_event_loop().time() * 1000)}"
    cancel_builder = InlineKeyboardBuilder()
    cancel_builder.row(types.InlineKeyboardButton(text="✖ Cancel Download", callback_data=f"cancel_download:{unique_task_id}"))

    task_output_dir = os.path.abspath(os.path.join("downloads", unique_task_id))
    task_temp_dir = f"{task_output_dir}_temp"
    process = None

    active_tasks[unique_task_id] = {
        "process": None,
        "cancelled": False,
        "user_id": user_id_local,
        "status_msg": status_msg
    }

    try:
        # Check non-premium limit before downloading
        async with async_session() as session:
            result = await session.exec(select(User).where(User.user_id == user_id_local))
            user = result.first()
            if not user:
                user = User(user_id=user_id_local)
                session.add(user)
                await session.commit()
                await session.refresh(user)

            if not user.is_premium:
                alac_count = await crud.get_alac_download_count_12h(session, user_id_local)
                if alac_count >= 100:
                    try:
                        await status_msg.edit_text("❌ ALAC download limit reached (100 tracks per 12 hours).")
                    except Exception:
                        pass
                    return

        progress_text = (
            f"🚀 {hbold('DOWNLOADING LOSSLESS (48kHz MAX)')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{make_progress_bar(completed_count, total_tracks)}\n"
            f"📥 Downloading {len(tracks_to_download)} remaining track(s)..."
        )
        try:
            await status_msg.edit_text(progress_text, reply_markup=cancel_builder.as_markup())
        except Exception:
            pass

        await asyncio.to_thread(os.makedirs, task_output_dir, exist_ok=True)
        await asyncio.to_thread(os.makedirs, task_temp_dir, exist_ok=True)

        cookies_path = os.path.abspath("cookies.txt")
        cookies_args = ["--cookies-path", cookies_path] if os.path.exists(cookies_path) else []

        process = await asyncio.create_subprocess_exec(
            "gamdl",
            *cookies_args,
            "--output-path", task_output_dir,
            "--temp-path", task_temp_dir,
            *tracks_to_download,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            limit=10 * 1024 * 1024,
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
                print(f"[gamdl Lossless] {line}")
                if "Requested format is not available" in line:
                    try:
                        process.terminate()
                        await process.wait()
                    except ProcessLookupError:
                        pass
                    try:
                        await status_msg.edit_text(
                            "⚠️ <b>Lossless (ALAC) format is not available</b> for this track/album.\n\n"
                            "👉 Please use <code>/aac &lt;link&gt;</code> to download in AAC 256kbps format.",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
                    return

            # Check for finalized .m4a files in output directory
            downloaded_files = await asyncio.to_thread(
                glob.glob, f"{task_output_dir}/**/*.m4a", recursive=True
            )

            for file_path in downloaded_files:
                norm_p = file_path.replace("\\", "/")
                filename = os.path.basename(norm_p)
                if "gamdl_temp" in norm_p or "_temp" in norm_p or filename.endswith("_encrypted.m4a") or filename.endswith(".tmp") or filename.endswith(".48k.m4a"):
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

                    async with async_session() as session:
                        result = await session.exec(select(User).where(User.user_id == user_id_local))
                        user = result.one()

                        if not user.is_premium:
                            alac_count = await crud.get_alac_download_count_12h(session, user_id_local)
                            if alac_count >= 100:
                                try:
                                    await msg.answer("❌ ALAC download limit reached (100 tracks per 12 hours). Stopping further downloads.")
                                except Exception:
                                    pass
                                try:
                                    process.terminate()
                                    await process.wait()
                                except ProcessLookupError:
                                    pass
                                return

                        # Check sample rate & remux Hi-Res to 48kHz ALAC if necessary
                        was_remuxed = await remux_to_48k_alac(file_path)

                        # Extract metadata & tags
                        track_title, artist, thumbnail, duration, isrc = await asyncio.to_thread(
                            utils.extract_track_metadata, file_path
                        )

                        # Upload and deliver audio
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
                            session.add(user)
                            await session.commit()

                            # Progress update
                            progress_text = (
                                f"🚀 {hbold('PROCESSING REGULAR LOSSLESS')}\n"
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

                                        # Only store standard original lossless in DB; DO NOT store remuxed tracks!
                                        if not was_remuxed:
                                            await crud.save_single_track(session=session, track_data=track_input, format_type="alac")
                                            await session.commit()

                                        # Log download history
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
                                            print(f"Failed to log Lossless download history: {le}")

                                        matched = True
                                        break

                            # 2. Fallback to title match
                            if not matched:
                                for original_track in songs:
                                    if utils.convert_text(original_track.title) == utils.convert_text(tbot.title):
                                        track_input = schema.TrackInputSchema(**original_track.model_dump())
                                        track_input.file_id = tbot.file_id
                                        track_input.file_unique_id = tbot.file_unique_id
                                        track_input.size = tbot.size
                                        track_input.chat_id = tbot.chat_id
                                        track_input.message_id = tbot.message_id

                                        # Only store standard original lossless in DB; DO NOT store remuxed tracks!
                                        if not was_remuxed:
                                            await crud.save_single_track(session=session, track_data=track_input, format_type="alac")
                                            await session.commit()

                                        # Log download history
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
                                            print(f"Failed to log Lossless download history: {le}")

                                        break

                        # Remove local downloaded/remuxed file
                        try:
                            await asyncio.to_thread(os.remove, file_path)
                        except Exception as e:
                            print(f"Failed to remove {file_path}: {e}")

            await asyncio.sleep(1)

        return_code = await process.wait()
        if not active_tasks.get(unique_task_id, {}).get("cancelled"):
            if return_code == 0:
                try:
                    await status_msg.edit_text(
                        "✅ All regular Lossless tracks processed successfully.\n\n"
                        "⚠️ <b>Notice:</b> The <code>/lossless</code> command is deprecated. Please use normal download (send link directly to chat) instead.\n\n"
                        "🌐 Link can be downloaded at: https://stream.eepy.in/"
                    )
                except Exception:
                    pass
            else:
                try:
                    await status_msg.edit_text(
                        "⚠ Some tracks might have failed to download.\n\n"
                        "⚠️ <b>Notice:</b> The <code>/lossless</code> command is deprecated. Please use normal download (send link directly to chat) instead.\n\n"
                        "🌐 Link can be downloaded at: https://stream.eepy.in/"
                    )
                except Exception:
                    pass

    except Exception as e:
        print(f"Error handling regular Lossless download: {e}")
        try:
            await msg.answer(f"⚠️ An unexpected error occurred during Lossless download: {str(e)}")
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
        for dir_to_clean in (task_output_dir, task_temp_dir):
            if await asyncio.to_thread(os.path.exists, dir_to_clean):
                try:
                    await asyncio.to_thread(shutil.rmtree, dir_to_clean)
                except Exception as e:
                    print(f"Failed to delete {dir_to_clean}: {e}")


async def lossless_worker() -> None:
    """
    Worker function to process the regular lossless download queue.
    """
    while True:
        task = await lossless_queue.get()
        user_id = task.get("user_id")
        msg = task.get("msg")

        if not user_id or not msg:
            lossless_queue.task_done()
            continue

        user_lock = lossless_locks.setdefault(user_id, asyncio.Lock())

        async with user_lock:
            try:
                await process_lossless_download(task)
            except Exception as e:
                print(f"Lossless worker caught execution exception for user {user_id}: {e}")
            finally:
                remaining = lossless_pending_jobs.get(user_id, 1) - 1
                if remaining <= 0:
                    lossless_pending_jobs.pop(user_id, None)
                    lossless_in_queue.discard(user_id)
                    lossless_locks.pop(user_id, None)
                else:
                    lossless_pending_jobs[user_id] = remaining
                lossless_queue.task_done()
