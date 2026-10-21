import asyncio
import os
import re
import time
import unicodedata
from typing import Tuple, Optional

from mutagen.mp4 import MP4
from aiogram.types import BufferedInputFile


def convert_text(s: str) -> str:
    """
    Normalizes a string by converting it to ASCII, removing accents, and stripping non-alphanumeric characters.
    
    Args:
        s: The input string to normalize.
        
    Returns:
        A normalized alphanumeric string in lowercase.
    """
    # 1. Decompose characters (e.g., 'é' becomes 'e' + '´')
    nfkd_form = unicodedata.normalize('NFKD', s)

    # 2. Strip out accents/diacritics and force lowercase
    only_ascii = nfkd_form.encode('ASCII', 'ignore').decode('utf-8').lower()

    # 3. Keep only core alphanumeric characters
    return "".join(re.findall(r'\w+', only_ascii))


def extract_track_metadata(file_path: str) -> Tuple[str, str, Optional[BufferedInputFile], Optional[int], Optional[str]]:
    """
    Extracts track metadata (title, artist, cover, duration, isrc) from .m4a/.m4v/.mp4/.flac/.mp3.
    
    Args:
        file_path: The path to the media file.
        
    Returns:
        A tuple containing (title, artist, thumbnail, duration, isrc).
    """
    fallback_stem = os.path.splitext(os.path.basename(file_path))[0]
    ext = os.path.splitext(file_path)[1].lower()

    try:
        if ext == ".flac":
            from mutagen.flac import FLAC
            audio = FLAC(file_path)
            title = audio.get("title", [fallback_stem])[0]
            artist = audio.get("artist", ["Unknown Artist"])[0]
            duration = int(audio.info.length) if audio.info else None
            isrc = audio.get("isrc", [None])[0]
            thumbnail = None
            if audio.pictures:
                thumbnail = BufferedInputFile(audio.pictures[0].data, filename="thumb.jpg")
            return title, artist, thumbnail, duration, isrc

        elif ext == ".mp3":
            from mutagen.mp3 import MP3
            audio = MP3(file_path)
            title = fallback_stem
            artist = "Unknown Artist"
            isrc = None
            thumbnail = None
            if audio.tags:
                title = str(audio.tags.get("TIT2", fallback_stem))
                artist = str(audio.tags.get("TPE1", "Unknown Artist"))
                if "TSRC" in audio.tags:
                    isrc = str(audio.tags["TSRC"])
                for frame in audio.tags.values():
                    if frame.FrameID == "APIC":
                        thumbnail = BufferedInputFile(frame.data, filename="thumb.jpg")
                        break
            duration = int(audio.info.length) if audio.info else None
            return title, artist, thumbnail, duration, isrc

        else:
            audio = MP4(file_path)
            artist = audio.tags.get('\xa9ART', ['Unknown Artist'])[0]
            title = audio.tags.get('\xa9nam', [fallback_stem])[0]
            duration = int(audio.info.length) if audio.info else None

            isrc = None
            if '----:com.apple.itunes:ISRC' in audio.tags:
                isrc_item = audio.tags['----:com.apple.itunes:ISRC'][0]
                try:
                    isrc = bytes(isrc_item).decode('utf-8', errors='ignore')
                except Exception:
                    isrc = str(isrc_item)

            thumbnail = None
            if 'covr' in audio.tags:
                cover_item = audio.tags['covr'][0]
                cover_data = bytes(cover_item)
                thumbnail = BufferedInputFile(cover_data, filename='thumb.jpg')
                
            return title, artist, thumbnail, duration, isrc
    except Exception as e:
        print(f"Failed to read metadata tags from {file_path}: {e}")
        return fallback_stem, "Unknown Artist", None, None, None


STORAGE_CHANNEL_ID_STR = os.getenv("STORAGE_CHANNEL_ID", "").strip().strip('"').strip("'")
if not STORAGE_CHANNEL_ID_STR:
    STORAGE_CHANNEL_ID = None
elif STORAGE_CHANNEL_ID_STR.startswith("@") or STORAGE_CHANNEL_ID_STR.startswith("http"):
    STORAGE_CHANNEL_ID = STORAGE_CHANNEL_ID_STR
else:
    try:
        STORAGE_CHANNEL_ID = int(STORAGE_CHANNEL_ID_STR)
    except ValueError:
        STORAGE_CHANNEL_ID = STORAGE_CHANNEL_ID_STR


async def upload_and_deliver_audio(
    bot,
    user_chat_id: int,
    file_path: str,
    title: str,
    performer: str,
    thumbnail=None,
    duration: Optional[int] = None
) -> Tuple[Optional[any], int, int]:
    """
    Sends the audio file directly to STORAGE_CHANNEL_ID first, then delivers a copy to user_chat_id.
    Returns (sent_user_msg, saved_chat_id, saved_message_id).
    """
    from aiogram.types import FSInputFile
    abs_path = os.path.abspath(file_path)

    if STORAGE_CHANNEL_ID:
        try:
            # 1. Upload directly to storage channel first
            channel_msg = await bot.send_audio(
                chat_id=STORAGE_CHANNEL_ID,
                audio=FSInputFile(abs_path),
                title=title,
                performer=performer,
                thumbnail=thumbnail,
                duration=duration
            )
            saved_chat_id = channel_msg.chat.id
            saved_message_id = channel_msg.message_id

            # 2. Copy/deliver to user's chat if different from storage channel
            if user_chat_id != STORAGE_CHANNEL_ID:
                await bot.copy_message(
                    chat_id=user_chat_id,
                    from_chat_id=STORAGE_CHANNEL_ID,
                    message_id=channel_msg.message_id
                )
            return channel_msg, saved_chat_id, saved_message_id
        except Exception as e:
            print(f"Direct channel upload failed for STORAGE_CHANNEL_ID ({STORAGE_CHANNEL_ID}): {e}")

    # Fallback to direct user PM answer
    user_msg = await bot.send_audio(
        chat_id=user_chat_id,
        audio=FSInputFile(abs_path),
        title=title,
        performer=performer,
        thumbnail=thumbnail,
        duration=duration
    )
    return user_msg, user_msg.chat.id, user_msg.message_id


async def upload_and_deliver_video(
    bot,
    user_chat_id: int,
    file_path: str,
    caption: str,
    thumbnail=None,
    duration: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    supports_streaming: bool = True
) -> Tuple[Optional[any], int, int]:
    """
    Sends the video file directly to STORAGE_CHANNEL_ID first, then delivers a copy to user_chat_id.
    Returns (sent_msg, saved_chat_id, saved_message_id).
    """
    from aiogram.types import FSInputFile
    abs_path = os.path.abspath(file_path)

    if STORAGE_CHANNEL_ID:
        try:
            # 1. Upload directly to storage channel first
            channel_msg = await bot.send_video(
                chat_id=STORAGE_CHANNEL_ID,
                video=FSInputFile(abs_path),
                caption=caption,
                parse_mode="HTML",
                thumbnail=thumbnail,
                duration=duration or 0,
                width=width,
                height=height,
                supports_streaming=supports_streaming
            )
            saved_chat_id = channel_msg.chat.id
            saved_message_id = channel_msg.message_id

            # 2. Copy/deliver to user's chat if different from storage channel
            if user_chat_id != STORAGE_CHANNEL_ID:
                await bot.copy_message(
                    chat_id=user_chat_id,
                    from_chat_id=STORAGE_CHANNEL_ID,
                    message_id=channel_msg.message_id
                )
            return channel_msg, saved_chat_id, saved_message_id
        except Exception as e:
            print(f"Direct channel video upload failed for STORAGE_CHANNEL_ID ({STORAGE_CHANNEL_ID}): {e}")

    # Fallback to direct user PM answer
    user_msg = await bot.send_video(
        chat_id=user_chat_id,
        video=FSInputFile(abs_path),
        caption=caption,
        parse_mode="HTML",
        thumbnail=thumbnail,
        duration=duration or 0,
        width=width,
        height=height,
        supports_streaming=supports_streaming
    )
    return user_msg, user_msg.chat.id, user_msg.message_id


async def copy_to_storage_channel(bot, sent_msg) -> Tuple[int, int]:
    """
    Copies sent_msg to the designated STORAGE_CHANNEL_ID.
    Returns (chat_id, message_id) of the target backup message.
    """
    if STORAGE_CHANNEL_ID and sent_msg:
        try:
            copied = await bot.copy_message(
                chat_id=STORAGE_CHANNEL_ID,
                from_chat_id=sent_msg.chat.id,
                message_id=sent_msg.message_id
            )
            return STORAGE_CHANNEL_ID, copied.message_id
        except Exception as e:
            print(f"Failed to copy message to STORAGE_CHANNEL_ID ({STORAGE_CHANNEL_ID}): {e}")

    return sent_msg.chat.id, sent_msg.message_id


GOFILE_TOKEN = os.getenv("GOFILE_TOKEN", "CR0Kk4oUyhz1I83ygKZWFIjZkxhZ8F9j")
_GOFILE_SALT = "12af056dacea0b"


def extract_gofile_content_id(url: str) -> Optional[str]:
    """Extracts the GoFile folder or file content ID from a link."""
    if not url:
        return None
    match = re.search(r"gofile\.io/d/([a-zA-Z0-9_-]+)", url)
    if match:
        return match.group(1)
    cleaned = url.strip()
    if re.fullmatch(r"[a-zA-Z0-9_-]{6,36}", cleaned):
        return cleaned
    return None


def _get_salt_via_node() -> str:
    """Dynamically extracts current GoFile salt from wt.obf.js if node is available."""
    try:
        import subprocess
        cmd = [
            "node", "-e",
            "const https = require('https');"
            "https.get('https://gofile.io/js/wt.obf.js', res => {"
            "  let d = ''; res.on('data', c => d += c);"
            "  res.on('end', () => {"
            "    global.window = global;"
            "    global.document = { querySelector: () => null, cookie: '' };"
            "    global.location = { href: 'https://gofile.io', hostname: 'gofile.io' };"
            "    global.navigator = { userAgent: 'test', language: 'en-US' };"
            "    eval(d + ';global.a0_0x4a47 = a0_0x4a47;');"
            "    console.log(global.a0_0x4a47(0x195, '\\x33\\x62\\x5d\\x25'));"
            "  });"
            "});"
        ]
        out = subprocess.check_output(cmd, text=True, timeout=8).strip()
        if out and len(out) >= 8:
            return out
    except Exception:
        pass
    return "12af056dacea0b"


async def is_gofile_link_alive(gofile_url: str, token: str = GOFILE_TOKEN) -> bool:
    """
    Checks whether a GoFile download link (e.g. https://gofile.io/d/XXXXXX) is still valid/alive.
    Returns True if content exists and is accessible.
    Returns False if the link has expired, been deleted, or is not found.
    """
    global _GOFILE_SALT
    content_id = extract_gofile_content_id(gofile_url)
    if not content_id:
        return False

    import aiohttp
    import hashlib

    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    lang = "en-US"

    for attempt in range(2):
        time_slot = int(time.time()) // 14400
        raw = f"{user_agent}::{lang}::{token}::{time_slot}::{_GOFILE_SALT}"
        wt = hashlib.sha256(raw.encode("utf-8")).hexdigest()

        headers = {
            "User-Agent": user_agent,
            "Accept-Language": lang,
            "X-BL": lang,
            "X-Website-Token": wt,
            "Authorization": f"Bearer {token}",
        }

        api_url = f"https://api.gofile.io/contents/{content_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        res = await resp.json()
                        st = res.get("status")
                        if st == "ok":
                            data = res.get("data", {})
                            if data.get("canAccess", True) is not False:
                                return True
                            return False
                        elif st == "error-token" and attempt == 0:
                            _GOFILE_SALT = await asyncio.to_thread(_get_salt_via_node)
                            continue
                        elif st == "error-notFound":
                            return False
                    elif resp.status in (404, 410):
                        return False
        except Exception as e:
            print(f"Error checking GoFile link aliveness for {gofile_url}: {e}")
            return False

    return False


async def upload_to_gofile_full(file_path: str, token: str = GOFILE_TOKEN) -> Optional[dict]:
    """
    Uploads a file to GoFile.io using the account token (via requests in a thread executor)
    and returns a file info dict with name, size, mimeType, downloadPage, and direct id.
    """
    if not os.path.exists(file_path):
        return None

    import requests
    loop = asyncio.get_running_loop()
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    def _do_upload():
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f, "application/octet-stream")}
            return requests.post(
                "https://upload.gofile.io/uploadfile",
                files=files,
                headers=headers,
                timeout=1800,
            )

    try:
        resp = await loop.run_in_executor(None, _do_upload)
        data = resp.json()
        if resp.status_code == 200 and data.get("status") == "ok":
            file_info = data.get("data", {})
            download_page = file_info.get("downloadPage")
            print(f"GoFile upload successful: {download_page}")
            return {
                "name": file_info.get("name", os.path.basename(file_path)),
                "size": file_info.get("size", os.path.getsize(file_path)),
                "mimeType": file_info.get("mimetype", "unknown"),
                "link": download_page,
                "downloadPage": download_page,
                "id": file_info.get("id"),
            }
        else:
            print(f"GoFile upload returned error: {data}")
    except Exception as e:
        print(f"Failed to upload {file_path} to GoFile: {e}")
    return None


async def upload_to_gofile(file_path: str, token: str = GOFILE_TOKEN) -> Optional[str]:
    """Uploads file to GoFile and returns downloadPage URL."""
    info = await upload_to_gofile_full(file_path, token=token)
    return info.get("downloadPage") if info else None


async def transcode_to_flac(input_path: str, remove_source: bool = False) -> Optional[str]:
    """
    Transcodes an audio file (e.g. ALAC/AAC .m4a) to lossless .flac using FFmpeg.
    Preserves all Vorbis tags (TITLE, ARTIST, ALBUM, TRACKNUMBER, DISCNUMBER, DATE, ISRC)
    and extracts/embeds the high-res album cover art into the FLAC container.
    Returns the path to the transcoded .flac file or None on failure.
    """
    if not os.path.exists(input_path):
        return None

    base, _ = os.path.splitext(input_path)
    output_flac = f"{base}.flac"

    # Extract tags and cover art from source .m4a
    title = None
    artist = None
    album = None
    isrc = None
    track_num = None
    disc_num = None
    date_val = None
    cover_data = None

    try:
        from mutagen.mp4 import MP4
        src = MP4(input_path)
        if src.tags:
            title = src.tags.get('\xa9nam', [None])[0]
            artist = src.tags.get('\xa9ART', [None])[0]
            album = src.tags.get('\xa9alb', [None])[0]
            date_val = src.tags.get('\xa9day', [None])[0]
            if 'trkn' in src.tags and src.tags['trkn']:
                track_num = str(src.tags['trkn'][0][0])
            if 'disk' in src.tags and src.tags['disk']:
                disc_num = str(src.tags['disk'][0][0])
            if '----:com.apple.itunes:ISRC' in src.tags:
                try:
                    isrc = bytes(src.tags['----:com.apple.itunes:ISRC'][0]).decode('utf-8', errors='ignore')
                except Exception:
                    isrc = str(src.tags['----:com.apple.itunes:ISRC'][0])
            if 'covr' in src.tags and src.tags['covr']:
                cover_data = bytes(src.tags['covr'][0])
    except Exception as e:
        print(f"[Transcode FLAC] Error reading source tags from {input_path}: {e}")

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-map", "0:a:0",
        "-c:a", "flac",
        "-compression_level", "8",
        output_flac
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            print(f"[Transcode FLAC] FFmpeg failed ({proc.returncode}): {stderr.decode('utf-8', errors='ignore')}")
            if os.path.exists(output_flac):
                try:
                    os.remove(output_flac)
                except Exception:
                    pass
            return None

        # Write Vorbis tags and Picture to FLAC
        def tag_flac():
            from mutagen.flac import FLAC, Picture
            audio = FLAC(output_flac)
            if title:
                audio["title"] = title
            if artist:
                audio["artist"] = artist
            if album:
                audio["album"] = album
            if track_num:
                audio["tracknumber"] = track_num
            if disc_num:
                audio["discnumber"] = disc_num
            if date_val:
                audio["date"] = str(date_val)
            if isrc:
                audio["isrc"] = isrc

            if cover_data:
                pic = Picture()
                pic.type = 3  # front cover
                pic.mime = "image/jpeg"
                pic.desc = "Front Cover"
                pic.data = cover_data
                audio.add_picture(pic)
            elif os.path.exists(os.path.join(os.path.dirname(input_path), "Cover.jpg")):
                try:
                    with open(os.path.join(os.path.dirname(input_path), "Cover.jpg"), "rb") as cf:
                        pic = Picture()
                        pic.type = 3
                        pic.mime = "image/jpeg"
                        pic.desc = "Front Cover"
                        pic.data = cf.read()
                        audio.add_picture(pic)
                except Exception:
                    pass
            audio.save()

        await asyncio.to_thread(tag_flac)

        if remove_source and os.path.exists(input_path) and input_path != output_flac:
            try:
                os.remove(input_path)
            except Exception:
                pass

        print(f"[Transcode FLAC] Successfully transcoded {input_path} -> {output_flac}")
        return output_flac
    except Exception as e:
        print(f"[Transcode FLAC] Exception: {e}")
        return None


async def transcode_to_mp3(input_path: str, bitrate: str = "320k", remove_source: bool = False) -> Optional[str]:
    """
    Transcodes an audio file (e.g. ALAC/AAC .m4a) to pristine MP3 (320kbps CBR) using FFmpeg.
    Preserves all ID3v2.3 tags and embeds album cover art (APIC).
    Returns the path to the transcoded .mp3 file or None on failure.
    """
    if not os.path.exists(input_path):
        return None

    base, _ = os.path.splitext(input_path)
    output_mp3 = f"{base}.mp3"

    # Extract tags and cover art from source .m4a
    title = None
    artist = None
    album = None
    isrc = None
    track_num = None
    disc_num = None
    date_val = None
    cover_data = None

    try:
        from mutagen.mp4 import MP4
        src = MP4(input_path)
        if src.tags:
            title = src.tags.get('\xa9nam', [None])[0]
            artist = src.tags.get('\xa9ART', [None])[0]
            album = src.tags.get('\xa9alb', [None])[0]
            date_val = src.tags.get('\xa9day', [None])[0]
            if 'trkn' in src.tags and src.tags['trkn']:
                track_num = str(src.tags['trkn'][0][0])
            if 'disk' in src.tags and src.tags['disk']:
                disc_num = str(src.tags['disk'][0][0])
            if '----:com.apple.itunes:ISRC' in src.tags:
                try:
                    isrc = bytes(src.tags['----:com.apple.itunes:ISRC'][0]).decode('utf-8', errors='ignore')
                except Exception:
                    isrc = str(src.tags['----:com.apple.itunes:ISRC'][0])
            if 'covr' in src.tags and src.tags['covr']:
                cover_data = bytes(src.tags['covr'][0])
    except Exception as e:
        print(f"[Transcode MP3] Error reading source tags from {input_path}: {e}")

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-map", "0:a:0",
        "-c:a", "libmp3lame",
        "-b:a", bitrate,
        "-id3v2_version", "3",
        output_mp3
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            print(f"[Transcode MP3] FFmpeg failed ({proc.returncode}): {stderr.decode('utf-8', errors='ignore')}")
            if os.path.exists(output_mp3):
                try:
                    os.remove(output_mp3)
                except Exception:
                    pass
            return None

        # Write ID3 tags and APIC picture to MP3
        def tag_mp3():
            from mutagen.mp3 import MP3
            from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TSRC, TRCK, TPOS, APIC, ID3NoHeaderError
            try:
                audio = MP3(output_mp3, ID3=ID3)
            except ID3NoHeaderError:
                audio = MP3(output_mp3)
                audio.add_tags()

            if title:
                audio.tags.add(TIT2(encoding=3, text=title))
            if artist:
                audio.tags.add(TPE1(encoding=3, text=artist))
            if album:
                audio.tags.add(TALB(encoding=3, text=album))
            if date_val:
                audio.tags.add(TDRC(encoding=3, text=str(date_val)))
            if isrc:
                audio.tags.add(TSRC(encoding=3, text=isrc))
            if track_num:
                audio.tags.add(TRCK(encoding=3, text=track_num))
            if disc_num:
                audio.tags.add(TPOS(encoding=3, text=disc_num))

            if cover_data:
                audio.tags.add(APIC(
                    encoding=3,
                    mime="image/jpeg",
                    type=3,  # Front cover
                    desc="Front Cover",
                    data=cover_data
                ))
            elif os.path.exists(os.path.join(os.path.dirname(input_path), "Cover.jpg")):
                try:
                    with open(os.path.join(os.path.dirname(input_path), "Cover.jpg"), "rb") as cf:
                        audio.tags.add(APIC(
                            encoding=3,
                            mime="image/jpeg",
                            type=3,
                            desc="Front Cover",
                            data=cf.read()
                        ))
                except Exception:
                    pass
            audio.save(v2_version=3)

        await asyncio.to_thread(tag_mp3)

        if remove_source and os.path.exists(input_path) and input_path != output_mp3:
            try:
                os.remove(input_path)
            except Exception:
                pass

        print(f"[Transcode MP3] Successfully transcoded {input_path} -> {output_mp3}")
        return output_mp3
    except Exception as e:
        print(f"[Transcode MP3] Exception: {e}")
        return None


async def transcode_audio(input_path: str, target_format: str = "flac", remove_source: bool = False) -> Optional[str]:
    """
    Transcodes input audio to the target format ('flac' or 'mp3').
    If format is already target or not recognized, returns input_path.
    """
    fmt = (target_format or "").lower().strip()
    if fmt == "flac":
        return await transcode_to_flac(input_path, remove_source=remove_source)
    elif fmt in ("mp3", "mp3_320k", "320k"):
        return await transcode_to_mp3(input_path, bitrate="320k", remove_source=remove_source)
    return input_path


async def create_album_zip(source_dir: str, output_zip_path: str) -> str:
    """
    Packages all tracks, covers, and lyric files from source_dir into output_zip_path using ZIP_STORED.
    """
    import zipfile

    def _zip_worker():
        with zipfile.ZipFile(output_zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
            for root, _, files in os.walk(source_dir):
                for f in files:
                    if f.endswith((".m4a", ".mp4", ".m4v", ".flac", ".jpg", ".png", ".lrc", ".srt", ".ttml", ".txt")):
                        full_path = os.path.join(root, f)
                        rel_path = os.path.relpath(full_path, source_dir)
                        zf.write(full_path, arcname=rel_path)
        return output_zip_path

    return await asyncio.to_thread(_zip_worker)


async def save_album_cover_and_lyrics(songs: list, target_dir: str) -> None:
    """
    Saves maximum resolution cover artwork (Cover.jpg) and all available lyrics (.lrc, .srt, .ttml) for each song.
    """
    import aiohttp
    from gamdlHelpUrl import get_api
    from gamdl.interface.song import AppleMusicSongInterface

    if not songs:
        return

    os.makedirs(target_dir, exist_ok=True)

    # 1. Download Max Resolution Cover Art
    first_song = songs[0]
    artwork_url = getattr(first_song, "artwork", None)
    if artwork_url:
        max_art_url = artwork_url.replace("1000x1000", "5000x5000").replace("{w}x{h}", "5000x5000")
        cover_path = os.path.join(target_dir, "Cover.jpg")
        if not os.path.exists(cover_path):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(max_art_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            with open(cover_path, "wb") as f:
                                f.write(content)
            except Exception as e:
                print(f"Failed to download max-res cover art: {e}")

    # 2. Fetch all lyrics formats (lrc, srt, ttml)
    try:
        api = await get_api()
        song_interface = AppleMusicSongInterface(api)

        lyrics_dir = os.path.join(target_dir, "Lyrics")
        os.makedirs(lyrics_dir, exist_ok=True)

        for idx, song in enumerate(songs, start=1):
            song_id = getattr(song, "song_id", None)
            if not song_id:
                continue

            try:
                webplayback = await api.get_webplayback(song_id)
                song_list = webplayback.get("songList", [])
                if not song_list:
                    continue
                
                assets = song_list[0].get("assets", [])
                ttml_content = None
                for asset in assets:
                    if asset.get("flavor") == "28:ttml" or asset.get("flavor") == "ttml":
                        # Fetch raw TTML from URL if available
                        ttml_url = asset.get("URL")
                        if ttml_url:
                            async with aiohttp.ClientSession() as l_session:
                                async with l_session.get(ttml_url, timeout=aiohttp.ClientTimeout(total=10)) as t_resp:
                                    if t_resp.status == 200:
                                        ttml_content = await t_resp.text()
                        break

                song_title = re.sub(r'[\\/*?:"<>|]', "", song.title or f"Track_{idx}")
                prefix = f"{idx:02d}. {song_title}"

                if ttml_content:
                    # Save raw TTML
                    with open(os.path.join(lyrics_dir, f"{prefix}.ttml"), "w", encoding="utf-8") as f:
                        f.write(ttml_content)

                    # Parse to LRC and SRT using gamdl's internal parser
                    try:
                        parsed_lyrics = song_interface._get_lyrics(ttml_content)
                        if parsed_lyrics and parsed_lyrics.synced:
                            # Save LRC
                            with open(os.path.join(lyrics_dir, f"{prefix}.lrc"), "w", encoding="utf-8") as f:
                                f.write(parsed_lyrics.synced)

                            # Save SRT if available
                            try:
                                srt_lines = song_interface._get_lyrics_line_srt(ttml_content)
                                if srt_lines:
                                    with open(os.path.join(lyrics_dir, f"{prefix}.srt"), "w", encoding="utf-8") as f:
                                        f.write(srt_lines)
                            except Exception:
                                pass
                    except Exception as pe:
                        print(f"Error parsing lyrics for {song_title}: {pe}")
            except Exception as le:
                print(f"Could not fetch lyrics for {song.title}: {le}")
    except Exception as e:
        print(f"Failed to fetch lyrics batch: {e}")


def human_size(num_bytes: float) -> str:
    """Format bytes to human readable string (KB, MB, GB, etc.)."""
    if not num_bytes or num_bytes <= 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.2f} TB"


async def upload_and_deliver_zip_document(
    bot,
    user_chat_id: int,
    file_path: str,
    caption: str,
    thumbnail=None
) -> Tuple[Optional[any], int, int, Optional[str], Optional[str], int]:
    """
    Sends the album ZIP document directly to STORAGE_CHANNEL_ID and user_chat_id.
    If file size > 2 GB or if Telegram upload fails, uploads to GoFile as fallback.
    Returns (sent_user_msg, saved_chat_id, saved_message_id, file_id, gofile_url, file_size).
    """
    from aiogram.types import FSInputFile
    abs_path = os.path.abspath(file_path)
    file_size = os.path.getsize(abs_path) if os.path.exists(abs_path) else 0

    # Ensure size is displayed in caption if not already present
    if file_size > 0 and "Size:" not in caption and "💾" not in caption:
        caption_lines = caption.split("\n")
        if len(caption_lines) >= 2:
            caption_lines.insert(2, f"💾 <b>Size:</b> {human_size(file_size)}")
            caption = "\n".join(caption_lines)
        else:
            caption = f"{caption}\n💾 <b>Size:</b> {human_size(file_size)}"

    # 2GB Telegram limit (2000 MB)
    max_tg_size = 2000 * 1024 * 1024

    if file_size > max_tg_size:
        print(f"Album ZIP {file_path} ({file_size} bytes) exceeds 2GB Telegram limit. Uploading to GoFile...")
        gofile_url = await upload_to_gofile(abs_path)
        return None, 0, 0, None, gofile_url, file_size

    # Size <= 2GB: Dual upload (both GoFile and Telegram)
    gofile_url = None
    try:
        print(f"Performing dual upload to GoFile for {file_path} ({file_size} bytes)...")
        gofile_url = await upload_to_gofile(abs_path)
    except Exception as ge:
        print(f"Dual GoFile upload failed: {ge}")

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    reply_markup = None
    if gofile_url:
        caption = f"{caption}\n🌐 <b>Fast Download (GoFile):</b> <a href='{gofile_url}'>High-Speed Link</a>"
        reply_markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Fast Download (GoFile)", url=gofile_url)]
        ])

    # Attempt Telegram Document Upload
    if STORAGE_CHANNEL_ID:
        try:
            channel_msg = await bot.send_document(
                chat_id=STORAGE_CHANNEL_ID,
                document=FSInputFile(abs_path),
                caption=caption,
                parse_mode="HTML",
                thumbnail=thumbnail,
                reply_markup=reply_markup
            )
            saved_chat_id = channel_msg.chat.id
            saved_message_id = channel_msg.message_id
            file_id = channel_msg.document.file_id if channel_msg.document else None

            user_msg = None
            if user_chat_id != STORAGE_CHANNEL_ID:
                user_msg = await bot.copy_message(
                    chat_id=user_chat_id,
                    from_chat_id=STORAGE_CHANNEL_ID,
                    message_id=channel_msg.message_id,
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=reply_markup
                )
            return user_msg or channel_msg, saved_chat_id, saved_message_id, file_id, gofile_url, file_size
        except Exception as e:
            print(f"Storage channel ZIP upload failed: {e}. Trying direct Telegram...")

    try:
        user_msg = await bot.send_document(
            chat_id=user_chat_id,
            document=FSInputFile(abs_path),
            caption=caption,
            parse_mode="HTML",
            thumbnail=thumbnail,
            reply_markup=reply_markup
        )
        file_id = user_msg.document.file_id if user_msg.document else None
        return user_msg, user_msg.chat.id, user_msg.message_id, file_id, gofile_url, file_size
    except Exception as e:
        print(f"Direct Telegram ZIP upload failed: {e}. Falling back to GoFile upload...")
        if not gofile_url:
            gofile_url = await upload_to_gofile(abs_path)
        return None, 0, 0, None, gofile_url, file_size


def __getattr__(name: str):
    """Dynamically exports bot instance from bot_control to prevent missing import errors."""
    if name == "bot":
        import bot_control
        return getattr(bot_control, "bot_instance", None)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")




