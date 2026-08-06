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
    Extracts track metadata (title, artist, cover, duration, isrc) directly from an .m4a file.
    
    Args:
        file_path: The path to the .m4a file.
        
    Returns:
        A tuple containing (title, artist, thumbnail, duration, isrc).
    """
    try:
        audio = MP4(file_path)

        artist = audio.tags.get('\xa9ART', ['Unknown Artist'])[0]
        title = audio.tags.get('\xa9nam', [os.path.basename(file_path).removesuffix('.m4a')])[0]
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
        fallback_title = os.path.basename(file_path).removesuffix(".m4a")
        return fallback_title, "Unknown Artist", None, None, None


STORAGE_CHANNEL_ID_STR = os.getenv("STORAGE_CHANNEL_ID", "-1004423011255")
try:
    STORAGE_CHANNEL_ID = int(STORAGE_CHANNEL_ID_STR) if STORAGE_CHANNEL_ID_STR else None
except ValueError:
    STORAGE_CHANNEL_ID = None


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


