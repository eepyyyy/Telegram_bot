import asyncio
import glob
import os
import re
import shutil
from datetime import datetime, timezone

from aiogram import Router, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from sqlmodel import select

import utils
import schema
import crud
import database
from database import User, async_session, MVTracks
from gamdlUrl import get_any_url
from queues import mv_queue, mv_in_queue, mv_pending_jobs, mv_locks, is_user_busy

mv = Router()


def build_mv_resolution_keyboard(song_id: str, cached_res_map: dict) -> InlineKeyboardMarkup:
    """
    Builds an interactive resolution selection inline keyboard for Telegram users.
    Shows which resolutions are already cached vs available for download.
    """
    resolutions = [
        ("2160p", "🎬 4K Ultra HD (2160p)"),
        ("1080p", "📺 1080p Full HD"),
        ("720p", "📱 720p HD"),
        ("480p", "💾 480p SD")
    ]
    keyboard = []
    for res_code, res_label in resolutions:
        if res_code in cached_res_map:
            text = f"✅ {res_label} (Instant)"
        else:
            text = f"⬇️ Download {res_label}"
        cb_data = f"dl_mv:{song_id}:{res_code}:h265"
        keyboard.append([InlineKeyboardButton(text=text, callback_data=cb_data)])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


@mv.callback_query(F.data.startswith("dl_mv:"))
async def handle_mv_resolution_callback(call: types.CallbackQuery) -> None:
    """
    Handles inline keyboard quality button clicks for Music Videos.
    """
    parts = call.data.split(":")
    if len(parts) < 4:
        await call.answer("Invalid callback data", show_alert=True)
        return

    song_id = parts[1]
    resolution = parts[2]
    codec = parts[3]
    user_id = call.from_user.id

    if is_user_busy(user_id):
        await call.answer("⏳ You already have an active download in progress.", show_alert=True)
        return

    async with async_session() as session:
        cached_mvs = await crud.get_mv_tracks_by_song_id(session, song_id)
        res_map = {m.resolution: m for m in cached_mvs if m.resolution and m.file_id}
        target = res_map.get(resolution)

        if target and target.file_id:
            await call.answer("🚀 Delivering cached video...")
            try:
                await call.message.answer_video(video=target.file_id, caption=f"🎬 <b>{target.title}</b> ({resolution.upper()})", parse_mode="HTML")
            except Exception as e:
                await call.answer(f"Failed to deliver: {e}", show_alert=True)
            return

        # Resolution not cached - trigger download
        target_url = cached_mvs[0].url if cached_mvs and cached_mvs[0].url else f"https://music.apple.com/us/music-video/{song_id}"
        await call.answer(f"⏳ Downloading Music Video in {resolution.upper()}...")
        await process_mv_enqueue(call.message, target_url, codec=codec, resolution=resolution)



def parse_mv_args(raw_args: str) -> tuple[str | None, str | None, str]:
    """
    Parses optional codec and resolution from /mv command arguments.
    Returns (resolution, codec, url).
    """
    tokens = raw_args.strip().split()
    if not tokens:
        return None, None, ""

    url = ""
    options = []
    for token in tokens:
        if re.fullmatch(r"https?://\S+", token):
            url = token
        else:
            options.append(token.lower())

    resolution = None
    codec = None

    for opt in options:
        if opt in ("4k", "2160p", "2160"):
            resolution = "2160p"
        elif opt in ("1440p", "1440"):
            resolution = "1440p"
        elif opt in ("1080p", "1080"):
            resolution = "1080p"
        elif opt in ("720p", "720"):
            resolution = "720p"
        elif opt in ("480p", "480"):
            resolution = "480p"
        elif opt in ("h265", "hevc"):
            codec = "h265"
        elif opt in ("h264", "avc"):
            codec = "h264"

    return resolution, codec, url


@mv.message(Command("mv"))
async def mv_download(msg: types.Message, command: CommandObject) -> None:
    """
    Command handler for downloading Apple Music Music Videos.
    Usage:
      /mv <Apple Music Video URL>
      /mv 4k <URL> or /mv 2160p <URL>
      /mv 1080p <URL>
      /mv h265 <URL>
      /mv 4k h265 <URL>
    """
    raw_args = (command.args or "").strip()
    resolution, codec, url = parse_mv_args(raw_args)

    if not re.fullmatch(r"https?://\S+", url):
        try:
            await msg.answer(
                "🎬 <b>Music Video Download Usage:</b>\n\n"
                "• <code>/mv &lt;Apple Music Video URL&gt;</code> (Auto best 4K H.265/HEVC)\n"
                "• <code>/mv 4k &lt;URL&gt;</code> or <code>/mv 2160p &lt;URL&gt;</code> (Force 4K)\n"
                "• <code>/mv 1080p &lt;URL&gt;</code> (Force 1080p)\n"
                "• <code>/mv h265 &lt;URL&gt;</code> (Force H.265 / HEVC)\n"
                "• <code>/mv h264 &lt;URL&gt;</code> (Force H.264 / AVC)\n"
                "• <code>/mv 4k h265 &lt;URL&gt;</code> (Force 4K H.265)",
                parse_mode="HTML"
            )
        except Exception:
            pass
        return

    await process_mv_enqueue(msg, url, codec=codec, resolution=resolution)


async def process_mv_enqueue(msg: types.Message, url: str, codec: str | None = None, resolution: str | None = None) -> None:
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

    # Mark user busy immediately to prevent race conditions during metadata fetch
    mv_in_queue.add(user_id_local)

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
            mv_in_queue.discard(user_id_local)
            try:
                await msg.answer("❌ Daily download limit reached.")
            except Exception:
                pass
            return

    status_msg = await msg.answer("🔍 Fetching Music Video metadata...")
    try:
        songs = await get_any_url(url)
    except Exception as e:
        mv_in_queue.discard(user_id_local)
        try:
            await status_msg.edit_text(f"❌ Failed to fetch metadata: {str(e)}")
        except Exception:
            pass
        return

    if not songs:
        mv_in_queue.discard(user_id_local)
        try:
            await status_msg.edit_text("❌ No music video content found.")
        except Exception:
            pass
        return

    song_obj = songs[0]
    song_id = song_obj.song_id if hasattr(song_obj, "song_id") else None
    title_str = song_obj.title if hasattr(song_obj, "title") and song_obj.title else "Music Video"
    artist_str = song_obj.artist if hasattr(song_obj, "artist") and song_obj.artist else ""

    # If no resolution specified, prompt user with interactive resolution selection keyboard
    if resolution is None and song_id:
        mv_in_queue.discard(user_id_local)
        async with async_session() as session:
            cached_mvs = await crud.get_mv_tracks_by_song_id(session, song_id)
            res_map = {m.resolution: m for m in cached_mvs if m.resolution and m.file_id}
            file_ids, _ = await crud.check_db_for_urls(songs, format_type="mv")
            if file_ids and not res_map:
                res_map["1080p"] = cached_mvs[0] if cached_mvs else True

        kb = build_mv_resolution_keyboard(song_id, res_map)
        try:
            await status_msg.edit_text(
                f"🎬 <b>{title_str}</b>\n👤 {artist_str}\n\nSelect your preferred resolution:",
                reply_markup=kb,
                parse_mode="HTML"
            )
        except Exception:
            pass
        return

    # Specific resolution requested (explicitly or via callback)
    async with async_session() as session:
        cached_mvs = await crud.get_mv_tracks_by_song_id(session, song_id) if song_id else []
        res_map = {m.resolution: m for m in cached_mvs if m.resolution and m.file_id}
        target = res_map.get(resolution) if resolution else None

    if target and target.file_id:
        mv_in_queue.discard(user_id_local)
        try:
            await msg.answer_video(video=target.file_id, caption=f"🎬 <b>{target.title or title_str}</b> ({resolution.upper()})", parse_mode="HTML")
            await status_msg.delete()
        except Exception:
            pass
        return

    # Queue the missing video track for requested resolution
    mv_pending_jobs[user_id_local] = len(songs)
    position = mv_queue.qsize()

    try:
        res_str = f" {resolution.upper()}" if resolution else " 4K"
        codec_str = f" ({codec.upper()})" if codec else " (H.265)"
        await status_msg.edit_text(f"🎬 Queued Music Video{res_str}{codec_str} at position #{position + 1}. Download starting...")
    except Exception:
        pass

    for track_url in [s.url for s in songs if s.url]:
        await mv_queue.put({
            "url": track_url,
            "songs": songs,
            "msg": msg,
            "user_id": user_id_local,
            "status_msg": status_msg,
            "codec": codec,
            "resolution": resolution,
        })



async def run_gamdl_mv_subprocess(output_dir: str, temp_dir: str, track_url: str, codec: str | None = None, resolution: str | None = None) -> tuple[int, bool]:
    """
    Executes gamdl for Music Video. Defaults to 2160p (4K) resolution and h265,h264 codec priority.
    Returns (return_code, format_unavailable).
    """
    cmd = [
        "gamdl",
        "-n",
        "--output-path", output_dir,
        "--temp-path", temp_dir,
        "--music-video-resolution", resolution or "2160p",
    ]
    if codec:
        cmd.extend(["--music-video-codec-priority", codec])
    else:
        cmd.extend(["--music-video-codec-priority", "h265,h264"])

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
    requested_resolution = task.get("resolution")

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

        return_code, format_unavailable = await run_gamdl_mv_subprocess(output_dir, temp_dir, track_url, requested_codec, requested_resolution)

        # Check for downloaded video files
        downloaded_files = []
        for ext in ("*.m4v", "*.mp4", "*.mkv", "*.webm"):
            found = await asyncio.to_thread(
                glob.glob, os.path.join(output_dir, "**", ext), recursive=True
            )
            downloaded_files.extend(found)

        valid_files = [
            f for f in downloaded_files
            if not ("gamdl_temp" in f.replace("\\", "/") or "_temp" in f.replace("\\", "/") or f.endswith(".tmp"))
        ]

        # Automatic fallback to yt-dlp if gamdl fails or format is unavailable
        if not valid_files or format_unavailable:
            print(f"[mv] Music Video format unavailable or no files produced for {track_url}. Initiating yt-dlp fallback...")
            try:
                await status_msg.edit_text("🎬 Music Video format unavailable. Trying yt-dlp fallback...")
            except Exception:
                pass

            ytdlp_cmd = [
                "yt-dlp",
                "--no-warning",
                "--output", os.path.join(output_dir, "%(title)s [%(id)s].%(ext)s"),
                track_url
            ]
            try:
                yt_proc = await asyncio.create_subprocess_exec(
                    *ytdlp_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                await yt_proc.communicate()
                print(f"[mv] yt-dlp fallback finished with exit code {yt_proc.returncode}")
            except Exception as e:
                print(f"[mv] yt-dlp fallback error: {e}")

            # Re-scan for downloaded video files after yt-dlp
            downloaded_files = []
            for ext in ("*.m4v", "*.mp4", "*.mkv", "*.webm"):
                found = await asyncio.to_thread(
                    glob.glob, os.path.join(output_dir, "**", ext), recursive=True
                )
                downloaded_files.extend(found)

            valid_files = [
                f for f in downloaded_files
                if not ("gamdl_temp" in f.replace("\\", "/") or "_temp" in f.replace("\\", "/") or f.endswith(".tmp"))
            ]

        if valid_files:

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
                            song_id=songs[0].song_id if songs else None,
                            file_id=file_id_val,
                            file_unique_id=file_uniq_val,
                            title=track_title,
                            artist=artist,
                            size=file_sz_val,
                            isrc=isrc,
                            chat_id=saved_chat_id,
                            message_id=saved_message_id,
                            resolution=requested_resolution or "2160p",
                            codec=requested_codec or "h265"
                        )
                        await crud.save_single_track(session, tbot, format_type="mv")
                        await session.commit()

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
