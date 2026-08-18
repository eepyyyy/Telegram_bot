import asyncio
import glob
import os
import re
import shutil
import json
import html
import requests
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

# Temporary maintenance flag (Set to True to enable, False to disable /mv command and link downloads)
MV_ENABLED = True

GOFILE_TOKEN = os.getenv("GOFILE_TOKEN", "CR0Kk4oUyhz1I83ygKZWFIjZkxhZ8F9j")


def human_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.2f} TB"


async def upload_to_gofile(file_path: str) -> dict:
    """Upload a file to gofile.io using the account token (via requests in a thread, to avoid
    an aiohttp streaming quirk against gofile's upload servers)."""
    headers = {"Authorization": f"Bearer {GOFILE_TOKEN}"} if GOFILE_TOKEN else {}
    loop = asyncio.get_running_loop()

    def _do_upload():
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f, "application/octet-stream")}
            return requests.post(
                "https://upload.gofile.io/uploadfile",
                files=files,
                headers=headers,
                timeout=600,
            )

    resp = await loop.run_in_executor(None, _do_upload)

    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(
            f"gofile returned non-JSON response (HTTP {resp.status_code}): {resp.text[:500]}"
        )

    if resp.status_code != 200 or data.get("status") != "ok":
        raise RuntimeError(f"gofile upload failed (HTTP {resp.status_code}): {data}")

    file_info = data["data"]
    return {
        "name": file_info.get("name", os.path.basename(file_path)),
        "size": file_info.get("size", os.path.getsize(file_path)),
        "mimeType": file_info.get("mimetype", "unknown"),
        "link": file_info.get("downloadPage"),
    }


async def get_video_metadata(file_path: str) -> dict:
    """Probe a video file for resolution, duration, fps, and codec info via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        file_path,
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await process.communicate()

    try:
        probe = json.loads(stdout)
    except json.JSONDecodeError:
        return {}

    video_stream = next(
        (s for s in probe.get("streams", []) if s.get("codec_type") == "video"), {}
    )
    duration_sec = float(probe.get("format", {}).get("duration", 0))
    minutes, seconds = divmod(int(duration_sec), 60)

    fps = None
    rate = video_stream.get("r_frame_rate", "")
    if "/" in rate:
        num, _, denom = rate.partition("/")
        try:
            denom_val = float(denom)
            fps = float(num) / denom_val if denom_val else None
        except ValueError:
            fps = None

    return {
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "codec": video_stream.get("codec_name", "unknown"),
        "fps": fps,
        "duration": f"{minutes}:{seconds:02d}",
    }



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
    if not MV_ENABLED:
        try:
            discord_markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💬 Join Discord Community", url="https://discord.gg/KBy2UMfjx8")]
            ])
            await msg.answer(
                "⚠️ Music Video downloads are temporarily out of service. Please join our Discord community for support and updates.",
                reply_markup=discord_markup
            )
        except Exception:
            pass
        return

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
    if not MV_ENABLED:
        try:
            discord_markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💬 Join Discord Community", url="https://discord.gg/KBy2UMfjx8")]
            ])
            await msg.answer(
                "⚠️ Music Video downloads are temporarily out of service. Please join our Discord community for support and updates.",
                reply_markup=discord_markup
            )
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

    tracks_to_download = [str(song.url) for song in songs if song.url]

    if not tracks_to_download:
        mv_in_queue.discard(user_id_local)
        try:
            await status_msg.edit_text("❌ No music video content found.")
        except Exception:
            pass
        return

    # Queue the missing video tracks
    mv_pending_jobs[user_id_local] = len(tracks_to_download)
    position = mv_queue.qsize()

    try:
        res_str = f" {resolution.upper()}" if resolution else " 4K"
        codec_str = f" ({codec.upper()})" if codec else " (H.265)"
        await status_msg.edit_text(f"🎬 Queued Music Video{res_str}{codec_str} at position #{position + 1}. Download starting...")
    except Exception:
        pass

    for track_url in tracks_to_download:
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

                    try:
                        await status_msg.edit_text(f"🚀 <b>Uploading to gofile.io</b>\n{html.escape(human_size(os.path.getsize(file_path)))}")
                    except Exception:
                        pass

                    try:
                        gofile_data, meta = await asyncio.gather(
                            upload_to_gofile(file_path),
                            get_video_metadata(file_path),
                        )
                    except Exception as e:
                        print(f"Failed to upload or get metadata: {e}")
                        gofile_data = None
                        meta = {}

                    if gofile_data:
                        resolution = f"{meta['width']}x{meta['height']}" if meta.get("width") else "unknown"
                        fps_str = f" @ {meta['fps']:.0f}fps" if meta.get("fps") else ""
                        name_str = f"{track_title} - {artist}" if track_title else gofile_data['name']

                        msg_text = (
                            f"🎬 <b>Music Video Downloaded</b>\n\n"
                            f"<b>Name:</b> <code>{html.escape(name_str)}</code>\n"
                            f"<b>Size:</b> {human_size(gofile_data['size'])}\n"
                            f"<b>Resolution:</b> {resolution}{fps_str}\n"
                            f"<b>Duration:</b> {meta.get('duration', 'unknown')}\n"
                            f"<b>Codec:</b> {html.escape(meta.get('codec', 'unknown'))}\n"
                            f"<b>Type:</b> <code>{html.escape(gofile_data['mimeType'])}</code>\n"
                            f"<b>Link:</b> {gofile_data['link']}"
                        )

                        sent_msg = await msg.answer(
                            msg_text,
                            link_preview_options=types.LinkPreviewOptions(is_disabled=True),
                        )
                    else:
                        sent_msg = None

                    if sent_msg and gofile_data:
                        user.download_count += 1
                        if not user.is_premium:
                            user.downloaded_today += 1
                        session.add(user)
                        await session.commit()

                        # Log download history
                        try:
                            matched_song_id = None
                            if isrc:
                                for s in songs:
                                    if s.isrc == isrc:
                                        matched_song_id = s.song_id
                                        break
                            if not matched_song_id:
                                for s in songs:
                                    if utils.convert_text(s.title) == utils.convert_text(track_title):
                                        matched_song_id = s.song_id
                                        break
                            if not matched_song_id and songs:
                                matched_song_id = songs[0].song_id

                            await crud.log_download(
                                session=session,
                                user_id=user_id_local,
                                song_id=matched_song_id,
                                format_type="mv",
                                size=gofile_data.get('size', 0),
                                is_cached=False
                            )
                            await session.commit()
                        except Exception as le:
                            print(f"Failed to log Music Video download: {le}")

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
