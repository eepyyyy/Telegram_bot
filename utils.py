import asyncio
import os
import re
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
    Extracts track metadata (title, artist, cover, duration, isrc) directly from an .m4a/.m4v/.mp4 file.
    
    Args:
        file_path: The path to the media file.
        
    Returns:
        A tuple containing (title, artist, thumbnail, duration, isrc).
    """
    try:
        audio = MP4(file_path)

        artist = audio.tags.get('\xa9ART', ['Unknown Artist'])[0]
        fallback_stem = os.path.splitext(os.path.basename(file_path))[0]
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
        fallback_title = os.path.splitext(os.path.basename(file_path))[0]
        return fallback_title, "Unknown Artist", None, None, None


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


async def upload_to_gofile(file_path: str, token: str = GOFILE_TOKEN) -> Optional[str]:
    """
    Uploads a file to GoFile.io using the REST API and returns the downloadPage URL.
    """
    import aiohttp
    if not os.path.exists(file_path):
        return None

    try:
        async with aiohttp.ClientSession() as session:
            # 1. Get best upload server
            async with session.get("https://api.gofile.io/servers", timeout=aiohttp.ClientTimeout(total=15)) as s_resp:
                s_data = await s_resp.json()
                if s_data.get("status") != "ok" or not s_data.get("data", {}).get("servers"):
                    server_name = "store1"
                else:
                    server_name = s_data["data"]["servers"][0]["name"]

            # 2. Upload file via multipart stream
            upload_url = f"https://{server_name}.gofile.io/contents/uploadfile"
            file_name = os.path.basename(file_path)
            
            with open(file_path, "rb") as f_obj:
                form = aiohttp.FormData()
                form.add_field("file", f_obj, filename=file_name)
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                
                async with session.post(
                    upload_url,
                    data=form,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=1800)  # 30 min for large files
                ) as up_resp:
                    result = await up_resp.json()
                    if result.get("status") == "ok":
                        download_page = result.get("data", {}).get("downloadPage")
                        print(f"GoFile upload successful: {download_page}")
                        return download_page
                    else:
                        print(f"GoFile upload error response: {result}")
    except Exception as e:
        print(f"Failed to upload {file_path} to GoFile: {e}")
    return None


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


async def upload_and_deliver_zip_document(
    bot,
    user_chat_id: int,
    file_path: str,
    caption: str,
    thumbnail=None
) -> Tuple[Optional[any], int, int, Optional[str], Optional[str]]:
    """
    Sends the album ZIP document directly to STORAGE_CHANNEL_ID and user_chat_id.
    If file size > 2 GB or if Telegram upload fails, uploads to GoFile as fallback.
    Returns (sent_user_msg, saved_chat_id, saved_message_id, file_id, gofile_url).
    """
    from aiogram.types import FSInputFile
    abs_path = os.path.abspath(file_path)
    file_size = os.path.getsize(abs_path) if os.path.exists(abs_path) else 0

    # 2GB Telegram limit (2000 MB)
    max_tg_size = 2000 * 1024 * 1024

    if file_size > max_tg_size:
        print(f"Album ZIP {file_path} ({file_size} bytes) exceeds 2GB Telegram limit. Uploading to GoFile...")
        gofile_url = await upload_to_gofile(abs_path)
        return None, 0, 0, None, gofile_url

    # Attempt Telegram Document Upload
    if STORAGE_CHANNEL_ID:
        try:
            channel_msg = await bot.send_document(
                chat_id=STORAGE_CHANNEL_ID,
                document=FSInputFile(abs_path),
                caption=caption,
                parse_mode="HTML",
                thumbnail=thumbnail
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
                    parse_mode="HTML"
                )
            return user_msg or channel_msg, saved_chat_id, saved_message_id, file_id, None
        except Exception as e:
            print(f"Storage channel ZIP upload failed: {e}. Trying direct or GoFile...")

    try:
        user_msg = await bot.send_document(
            chat_id=user_chat_id,
            document=FSInputFile(abs_path),
            caption=caption,
            parse_mode="HTML",
            thumbnail=thumbnail
        )
        file_id = user_msg.document.file_id if user_msg.document else None
        return user_msg, user_msg.chat.id, user_msg.message_id, file_id, None
    except Exception as e:
        print(f"Direct Telegram ZIP upload failed: {e}. Falling back to GoFile upload...")
        gofile_url = await upload_to_gofile(abs_path)
        return None, 0, 0, None, gofile_url



