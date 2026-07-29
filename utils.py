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

