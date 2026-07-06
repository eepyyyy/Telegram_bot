import unicodedata
import re, os
from mutagen.mp4 import MP4
from aiogram.types import FSInputFile, BufferedInputFile

def convert_text(s: str) -> str:
    """
        Takes any Language string and converts to alphanumeric characters in Unicode
    Args:
        s: String input
    Returns:
        alphanumeric characters in Unicode
    """
    # 1. Decompose characters (e.g., 'é' becomes 'e' + '´')
    nfkd_form = unicodedata.normalize('NFKD', s)

    # 2. Strip out accents/diacritics and force lowercase
    only_ascii = nfkd_form.encode('ASCII', 'ignore').decode('utf-8').lower()

    # 3. Keep only core alphanumeric characters across any language script
    #    \w matches alphanumeric characters in Unicode
    return "".join(re.findall(r'\w+', only_ascii))

def extract_track_metadata(file_path: str):
    """
        Extracts pristine tags directly from the .m4a metadata container.
        No regex, no filename string stripping.
    """
    try:
        audio = MP4(file_path)

        artist = audio.tags.get('\xa9ART', ['Unknown Artist'])[0]

        title = audio.tags.get('\xa9nam', [os.path.basename(file_path).removesuffix('.m4a')])[0]

        duration = int(audio.info.length) if audio.info else None

        thumbnail = None
        if 'covr' in audio.tags:
            cover_item = audio.tags['covr'][0]
            cover_data = bytes(cover_item)
            thumbnail = BufferedInputFile(cover_data, filename='thumb.jpg')
        return title, artist, thumbnail, duration
    except Exception as e:
        print(f"Failed to read metadata tags: {e}")
        fallback_title = os.path.basename(file_path).removesuffix(".m4a")
        return fallback_title, "Unknown Artist", None, None
