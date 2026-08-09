import sys
import asyncio
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse, parse_qs

# Ensure stdout/stderr handle UTF-8 symbols safely on Windows
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from gamdl.api import AppleMusicApi
from gamdl.interface import AppleMusicInterface

_api_instance: Optional[AppleMusicApi] = None
_api_lock: Optional[asyncio.Lock] = None
_api_loop: Optional[asyncio.AbstractEventLoop] = None


async def get_api() -> AppleMusicApi:
    """
    Returns a shared AppleMusicApi instance, initializing it if necessary.
    Ensures the instance is valid for the current event loop.
    """
    global _api_instance, _api_lock, _api_loop
    current_loop = asyncio.get_running_loop()

    if _api_loop != current_loop:
        _api_instance = None
        _api_lock = asyncio.Lock()
        _api_loop = current_loop

    async with _api_lock:
        if _api_instance is None:
            _api_instance = await AppleMusicApi.create_from_netscape_cookies("./cookies.txt")
        return _api_instance


def get_artwork_url(artwork_dict: Optional[dict], size: int = 1000) -> Optional[str]:
    """
    Extracts the artwork URL from the dictionary and replaces size placeholders.
    """
    if not artwork_dict:
        return None
    url = artwork_dict.get("url")
    if not url:
        return None
    return url.replace("{w}", str(size)).replace("{h}", str(size))


def format_duration(duration_ms: Optional[int]) -> str:
    """
    Formats milliseconds into mm:ss or hh:mm:ss.
    """
    if not duration_ms:
        return "N/A"
    seconds = int(duration_ms // 1000)
    minutes = seconds // 60
    rem_seconds = seconds % 60
    hours = minutes // 60
    rem_minutes = minutes % 60
    if hours > 0:
        return f"{hours}:{rem_minutes:02d}:{rem_seconds:02d}"
    return f"{rem_minutes}:{rem_seconds:02d}"


def normalize_apple_music_url(url: str, default_storefront: str = "us") -> str:
    """
    Ensures an Apple Music URL contains a valid storefront region tag (e.g. /us/ or /in/).
    If missing (e.g. https://music.apple.com/song/1117420388), inserts the default storefront.
    """
    if not url:
        return url
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    
    path_parts = [p for p in parsed.path.split("/") if p]
    if not path_parts:
        return url

    if path_parts[0].lower() in ("song", "album", "artist", "playlist"):
        new_path = f"/{default_storefront}/" + "/".join(path_parts)
        url_without_query = f"{parsed.scheme}://{parsed.netloc}{new_path}"
        if parsed.query:
            return f"{url_without_query}?{parsed.query}"
        return url_without_query

    return url


def album_url_to_song_url(url: str) -> str:
    """
    Converts an Apple Music album URL with a song parameter to a direct song URL.
    """
    if not url:
        return ""
    try:
        url = normalize_apple_music_url(url)
        parsed = urlparse(url)
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if len(parts) < 3:
            return url
        storefront = parts[0] if len(parts[0]) == 2 else "us"
        slug = parts[2] if len(parts) > 2 else "song"
        query = parse_qs(parsed.query)
        song_id = query.get("i", [parts[-1]])[0]
        return f"https://music.apple.com/{storefront}/song/{slug}/{song_id}"
    except Exception:
        return url


def parse_available_formats(audio_traits: Optional[List[str]]) -> Dict[str, Any]:
    """
    Parses audioTraits into availability status for AAC, ALAC Lossless, Hi-Res Lossless, and Dolby Atmos.
    """
    traits = [t.lower() for t in (audio_traits or [])]

    has_aac = True  # AAC 256kbps is standard for all Apple Music catalog items
    has_hi_res = "hi-res-lossless" in traits
    has_alac = "lossless" in traits or has_hi_res
    has_atmos = any(t in traits for t in ["spatial", "atmos", "dolby-atmos", "dolby-audio"])

    formats_list = []
    formats_list.append("• <b>AAC (256kbps):</b> ✅ Available (<code>/aac &lt;url&gt;</code>)")

    if has_hi_res:
        formats_list.append("• <b>ALAC (Hi-Res Lossless 24-bit/192kHz):</b> ✅ Available (send link directly)")
    elif has_alac:
        formats_list.append("• <b>ALAC (Lossless 24-bit/48kHz):</b> ✅ Available (send link directly)")
    else:
        formats_list.append("• <b>ALAC (Lossless):</b> ❌ Not Available")

    if has_atmos:
        formats_list.append("• <b>Dolby Atmos (Spatial Audio):</b> ✅ Available (<code>/atmos &lt;url&gt;</code>)")
    else:
        formats_list.append("• <b>Dolby Atmos (Spatial Audio):</b> ❌ Not Available")

    return {
        "has_aac": has_aac,
        "has_alac": has_alac,
        "has_hi_res": has_hi_res,
        "has_atmos": has_atmos,
        "formats_text": "\n".join(formats_list)
    }


def extract_song_id_from_url(url: str) -> str:
    """
    Extracts the song ID from an Apple Music URL.
    """
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    query = parse_qs(parsed.query)
    return query.get("i", [parts[-1]])[0]


async def get_song_metadata(url: str) -> Dict[str, Any]:
    """
    Fetches detailed metadata for a single song.
    """
    url = normalize_apple_music_url(url)
    api = await get_api()
    song_id = extract_song_id_from_url(url)

    song = await api.get_song(song_id)
    if not song or "data" not in song or not song["data"]:
        raise ValueError(f"Song with ID {song_id} not found.")

    data = song["data"][0]
    attrs = data.get("attributes", {})

    album_id = "N/A"
    try:
        album_id = data["relationships"]["albums"]["data"][0]["id"]
    except Exception:
        pass

    href_parts = data.get("href", "").split("/")
    storefront = href_parts[3] if len(href_parts) > 3 else "us"

    audio_traits = attrs.get("audioTraits", [])
    formats_info = parse_available_formats(audio_traits)

    return {
        "type": "song",
        "song_id": data.get("id", song_id),
        "title": attrs.get("name", "Unknown Track"),
        "artist": attrs.get("artistName", "Unknown Artist"),
        "album": attrs.get("albumName", "Unknown Album"),
        "album_id": album_id,
        "release_date": attrs.get("releaseDate", "N/A"),
        "duration": format_duration(attrs.get("durationInMillis")),
        "duration_ms": attrs.get("durationInMillis"),
        "track_number": attrs.get("trackNumber"),
        "disc_number": attrs.get("discNumber"),
        "isrc": attrs.get("isrc", "N/A"),
        "composer": attrs.get("composerName", "N/A"),
        "genres": attrs.get("genreNames", []),
        "is_explicit": attrs.get("contentRating") == "explicit",
        "audio_traits": audio_traits,
        "formats_info": formats_info,
        "url": attrs.get("url", url),
        "storefront": storefront,
        "artwork": get_artwork_url(attrs.get("artwork")),
    }


async def get_album_metadata(url: str) -> Dict[str, Any]:
    """
    Fetches comprehensive metadata for an album and all its tracks.
    """
    url = normalize_apple_music_url(url)
    api = await get_api()
    info = AppleMusicInterface.get_url_info(url)
    album_id = info.id

    album = await api.get_album(album_id)
    if not album or "data" not in album or not album["data"]:
        raise ValueError(f"Album with ID {album_id} not found.")

    album_node = album["data"][0]
    attrs = album_node.get("attributes", {})
    tracks_data = album_node.get("relationships", {}).get("tracks", {}).get("data", [])

    href_parts = album_node.get("href", "").split("/")
    storefront = href_parts[3] if len(href_parts) > 3 else "us"

    audio_traits = attrs.get("audioTraits", [])
    formats_info = parse_available_formats(audio_traits)

    tracks = []
    for track in tracks_data:
        if track.get("type") != "songs":
            continue
        t_attrs = track.get("attributes", {})
        raw_t_url = t_attrs.get("url", "")
        track_url = album_url_to_song_url(raw_t_url) if raw_t_url else ""
        tracks.append({
            "song_id": track.get("id"),
            "track_number": t_attrs.get("trackNumber"),
            "title": t_attrs.get("name", "Unknown Track"),
            "artist": t_attrs.get("artistName", attrs.get("artistName", "Unknown Artist")),
            "duration": format_duration(t_attrs.get("durationInMillis")),
            "isrc": t_attrs.get("isrc", "N/A"),
            "is_explicit": t_attrs.get("contentRating") == "explicit",
            "url": track_url
        })

    return {
        "type": "album",
        "album_id": album_node.get("id", album_id),
        "title": attrs.get("name", "Unknown Album"),
        "artist": attrs.get("artistName", "Unknown Artist"),
        "release_date": attrs.get("releaseDate", "N/A"),
        "track_count": attrs.get("trackCount", len(tracks)),
        "genres": attrs.get("genreNames", []),
        "record_label": attrs.get("recordLabel", "N/A"),
        "copyright": attrs.get("copyright", "N/A"),
        "upc": attrs.get("upc", "N/A"),
        "is_explicit": attrs.get("contentRating") == "explicit",
        "audio_traits": audio_traits,
        "formats_info": formats_info,
        "url": attrs.get("url", url),
        "storefront": storefront,
        "artwork": get_artwork_url(attrs.get("artwork")),
        "tracks": tracks,
    }


async def get_artist_metadata(url: str) -> Dict[str, Any]:
    """
    Fetches comprehensive metadata for an artist and lists albums grouped by category.
    """
    url = normalize_apple_music_url(url)
    api = await get_api()
    info = AppleMusicInterface.get_url_info(url)
    artist_id = info.id

    artist = await api.get_artist(artist_id=artist_id)
    if not artist or "data" not in artist or not artist["data"]:
        raise ValueError(f"Artist with ID {artist_id} not found.")

    artist_data = artist["data"][0]
    attrs = artist_data.get("attributes", {})

    href_parts = artist_data.get("href", "").split("/")
    storefront = href_parts[3] if len(href_parts) > 3 else "us"

    selection = {
        "Full Albums": [],
        "Singles & EPs": [],
        "Live Albums": [],
        "Compilations": [],
    }

    views_mapping = {
        "full-albums": "Full Albums",
        "singles": "Singles & EPs",
        "live-albums": "Live Albums",
        "compilation-albums": "Compilations",
    }

    views = artist_data.get("views", {})
    for sec_key, sec_title in views_mapping.items():
        sec_data = views.get(sec_key, {}).get("data", [])
        for album_item in sec_data:
            a_attrs = album_item.get("attributes", {})
            selection[sec_title].append({
                "name": a_attrs.get("name", "Unknown Album"),
                "release_date": a_attrs.get("releaseDate", "N/A"),
                "track_count": a_attrs.get("trackCount"),
                "url": a_attrs.get("url", ""),
            })

    return {
        "type": "artist",
        "artist_id": artist_data.get("id", artist_id),
        "name": attrs.get("name", "Unknown Artist"),
        "genres": attrs.get("genreNames", []),
        "url": attrs.get("url", url),
        "storefront": storefront,
        "artwork": get_artwork_url(attrs.get("artwork")),
        "categories": selection
    }


async def get_playlist_metadata(url: str) -> Dict[str, Any]:
    """
    Fetches comprehensive metadata for a playlist and its tracklist.
    """
    url = normalize_apple_music_url(url)
    api = await get_api()
    info = AppleMusicInterface.get_url_info(url)
    playlist_id = info.id

    playlist = await api.get_playlist(playlist_id)
    if not playlist or "data" not in playlist or not playlist["data"]:
        raise ValueError(f"Playlist with ID {playlist_id} not found.")

    playlist_node = playlist["data"][0]
    attrs = playlist_node.get("attributes", {})
    tracks_data = playlist_node.get("relationships", {}).get("tracks", {}).get("data", [])

    href_parts = playlist_node.get("href", "").split("/")
    storefront = href_parts[3] if len(href_parts) > 3 else "us"

    tracks = []
    for track in tracks_data:
        if track.get("type") != "songs":
            continue
        t_attrs = track.get("attributes", {})
        raw_t_url = t_attrs.get("url", "")
        track_url = album_url_to_song_url(raw_t_url) if raw_t_url else ""
        tracks.append({
            "song_id": track.get("id"),
            "title": t_attrs.get("name", "Unknown Track"),
            "artist": t_attrs.get("artistName", "Unknown Artist"),
            "album": t_attrs.get("albumName", "Unknown Album"),
            "duration": format_duration(t_attrs.get("durationInMillis")),
            "isrc": t_attrs.get("isrc", "N/A"),
            "is_explicit": t_attrs.get("contentRating") == "explicit",
            "url": track_url
        })

    desc = attrs.get("description", {})
    description_text = desc.get("standard") if isinstance(desc, dict) else None

    return {
        "type": "playlist",
        "playlist_id": playlist_node.get("id", playlist_id),
        "title": attrs.get("name", "Unknown Playlist"),
        "curator": attrs.get("curatorName", "Apple Music"),
        "description": description_text,
        "last_modified": attrs.get("lastModifiedDate", "N/A"),
        "track_count": len(tracks),
        "url": attrs.get("url", url),
        "storefront": storefront,
        "artwork": get_artwork_url(attrs.get("artwork")),
        "tracks": tracks,
    }


async def get_url_metadata(url: str) -> Dict[str, Any]:
    """
    Determines URL type (song, album, artist, or playlist) and fetches detailed metadata.
    """
    url = normalize_apple_music_url(url)
    info = AppleMusicInterface.get_url_info(url)

    if info.type == "album":
        if info.sub_id:
            return await get_song_metadata(url)
        return await get_album_metadata(url)

    if info.type == "artist":
        return await get_artist_metadata(url)

    if info.type == "playlist":
        return await get_playlist_metadata(url)

    if info.type == "song":
        return await get_song_metadata(url)

    raise ValueError(f"Unsupported URL type: {info.type}")
