import asyncio
import glob
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional

import crud
import database
import schema
import utils
from web import config

logger = logging.getLogger("web.downloader")

# Active download locks per (format_type, song_id/url) to avoid duplicate concurrent gamdl processes
_download_locks: Dict[str, asyncio.Lock] = {}
_global_lock = asyncio.Lock()


async def get_download_lock(key: str) -> asyncio.Lock:
    async with _global_lock:
        if key not in _download_locks:
            _download_locks[key] = asyncio.Lock()
        return _download_locks[key]


def get_codec_args(format_type: str) -> List[str]:
    fmt = format_type.lower()
    if fmt == "aac":
        return ["--song-codec-priority", "aac-web"]
    elif fmt == "atmos":
        return ["--song-codec-priority", "atmos"]
    elif fmt in ("mv", "video"):
        return ["--music-video-resolution", "2160p", "--music-video-codec-priority", "h265,h264"]
    else:  # alac (default)
        return []


def get_target_subfolder(format_type: str) -> str:
    fmt = format_type.lower()
    if fmt in ("aac", "atmos", "mv", "video", "alac"):
        return fmt if fmt != "video" else "mv"
    return "alac"


async def download_track_web(
    url: str,
    format_type: str = "alac",
    resolution: Optional[str] = None,
    codec: Optional[str] = None
) -> Dict[str, Any]:
    """
    Downloads an Apple Music track or album using gamdl directly to the local storage directory (./downloads).
    Indexes downloaded files into PostgreSQL database using shared CRUD functions.
    """
    format_type = format_type.lower()
    target_subfolder = get_target_subfolder(format_type)
    lock_key = f"{format_type}:{resolution}:{codec}:{url}"
    lock = await get_download_lock(lock_key)

    async with lock:
        # Determine temporary workspace
        timestamp = int(asyncio.get_event_loop().time() * 1000)
        temp_dir = config.LOCAL_STORAGE_DIR / "temp" / f"web_{timestamp}"
        output_dir = temp_dir / "out"
        temp_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        cookies_file = config.BASE_DIR / "cookies.txt"
        cookies_arg = ["--cookies-path", str(cookies_file)] if cookies_file.exists() else []

        extra_args = []
        if target_subfolder == "mv":
            extra_args.extend(["--music-video-resolution", resolution or "2160p"])
            if codec:
                extra_args.extend(["--music-video-codec-priority", codec])
            else:
                extra_args.extend(["--music-video-codec-priority", "h265,h264"])

        cmd = [
            "gamdl",
            "-n",
            *cookies_arg,
            "--output-path", str(output_dir),
            "--temp-path", str(temp_dir),
            *get_codec_args(format_type),
            *extra_args,
            url
        ]


        logger.info(f"[Web Downloader] Executing: {' '.join(cmd)}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        stdout, _ = await process.communicate()
        output_log = stdout.decode("utf-8", errors="ignore") if stdout else ""
        logger.info(f"[Web Downloader] Process finished with exit code {process.returncode}")

        # Scan for output files
        extensions = ["*.m4a", "*.mp4", "*.caf", "*.m4v", "*.mkv", "*.webm"]
        downloaded_files = []
        for ext in extensions:
            downloaded_files.extend(glob.glob(os.path.join(str(output_dir), "**", ext), recursive=True))

        valid_files = []
        for fp in downloaded_files:
            norm = fp.replace("\\", "/")
            fname = os.path.basename(norm)
            if "gamdl_temp" in norm or "_temp" in norm or fname.endswith("_encrypted.m4a") or fname.endswith(".tmp"):
                continue
            valid_files.append(fp)

        format_unavailable = "Requested format is not available" in output_log

        # Automatic fallback to yt-dlp if gamdl fails or requested format is not available
        if not valid_files or format_unavailable:
            logger.info(f"[Web Downloader] gamdl format unavailable or no files produced. Launching yt-dlp fallback for {url}...")
            ytdlp_cmd = [
                "yt-dlp",
                "--no-warning",
                "--output", os.path.join(str(output_dir), "%(title)s [%(id)s].%(ext)s"),
                url
            ]
            try:
                yt_proc = await asyncio.create_subprocess_exec(
                    *ytdlp_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                yt_out, _ = await yt_proc.communicate()
                logger.info(f"[Web Downloader] yt-dlp fallback finished with exit code {yt_proc.returncode}")
            except Exception as e:
                logger.error(f"[Web Downloader] yt-dlp fallback error: {e}")

            # Re-scan output files after yt-dlp fallback
            downloaded_files = []
            for ext in extensions:
                downloaded_files.extend(glob.glob(os.path.join(str(output_dir), "**", ext), recursive=True))

            valid_files = []
            for fp in downloaded_files:
                norm = fp.replace("\\", "/")
                fname = os.path.basename(norm)
                if "gamdl_temp" in norm or "_temp" in norm or fname.endswith("_encrypted.m4a") or fname.endswith(".tmp"):
                    continue
                valid_files.append(fp)

        if not valid_files:
            # Clean temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)
            return {
                "success": False,
                "error": "No media files were generated by gamdl or yt-dlp. Requested format might be unavailable or URL invalid.",
                "log": output_log[-1000:] if output_log else ""
            }


        dest_folder = config.LOCAL_STORAGE_DIR / target_subfolder
        dest_folder.mkdir(parents=True, exist_ok=True)

        results = []
        for file_path in valid_files:
            fname = os.path.basename(file_path)
            dest_path = dest_folder / fname

            # Move file to permanent storage folder
            shutil.move(file_path, dest_path)

            # Parse metadata using mutagen (utils.py)
            title, artist, _thumb, _duration, isrc = utils.extract_track_metadata(str(dest_path))
            file_size = os.path.getsize(dest_path)

            title = title or Path(fname).stem
            artist = artist or "Unknown Artist"
            album = "Unknown Album"
            isrc = isrc or ""


            # Standardize song_id from URL or filename
            song_id_match = re.search(r"i=(\d+)|/song/(?:[^/]+/)?(\d+)", url)
            song_id = song_id_match.group(1) or song_id_match.group(2) if song_id_match else isrc or str(timestamp)

            # Insert/Update PostgreSQL database record
            track_schema = schema.TrackInputSchema(
                song_id=song_id,
                title=title,
                artist=artist,
                album=album,
                isrc=isrc,
                url=url,
                chat_id=0,
                message_id=None,
                file_id="",
                artwork="",
                size=file_size,
                resolution=resolution,
                codec=codec
            )


            async with database.async_session() as session:
                await crud.save_single_track(session, track_schema, format_type=target_subfolder)
                await session.commit()


            results.append({
                "song_id": song_id,
                "title": title,
                "artist": artist,
                "album": album,
                "format": target_subfolder,
                "filename": fname,
                "size": file_size,
                "file_path": str(dest_path),
                "download_url": f"/download/{target_subfolder}/{song_id}",
                "stream_url": f"/stream/{target_subfolder}/{song_id}"
            })

        # Cleanup temp workspace
        shutil.rmtree(temp_dir, ignore_errors=True)

        return {
            "success": True,
            "count": len(results),
            "tracks": results
        }
