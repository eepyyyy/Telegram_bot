import sys
import asyncio
from typing import List, Optional, Dict
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

from schema import TrackInputSchema

# Shared API instance to avoid repeated initialization.
# We store the instance, the lock, and the loop to handle multiple event loops safely.
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

    # If the loop has changed (e.g., between asyncio.run calls), reset the singleton
    if _api_loop != current_loop:
        _api_instance = None
        _api_lock = asyncio.Lock()
        _api_loop = current_loop

    async with _api_lock:
        if _api_instance is None:
            # Assumes cookies.txt is in the root directory
            _api_instance = await AppleMusicApi.create_from_netscape_cookies("./cookies.txt")
        return _api_instance


def get_artwork_url(artwork_dict: Optional[dict]) -> Optional[str]:
    """
    Extracts the artwork URL from the dictionary and replaces the size placeholders.
    """
    if not artwork_dict:
        return None
    url = artwork_dict.get("url")
    if not url:
        return None
    return url.replace("{w}", "1000").replace("{h}", "1000")


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

    # If first path segment is song, album, artist, playlist (missing 2-letter storefront tag)
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
    url = normalize_apple_music_url(url)
    parsed = urlparse(url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]

    storefront = parts[0] if len(parts) > 0 and len(parts[0]) == 2 else "us"
    slug = parts[2] if len(parts) > 2 else "song"

    query = parse_qs(parsed.query)
    song_id = query.get("i", [parts[-1]])[0]

    return f"https://music.apple.com/{storefront}/song/{slug}/{song_id}"


def extract_song_id_from_url(url: str) -> str:
    """
    Extracts the song ID from an Apple Music URL.
    """
    url = normalize_apple_music_url(url)
    parsed = urlparse(url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    query = parse_qs(parsed.query)

    return query.get("i", [parts[-1]])[0]


def extract_album_id_from_url(url: str) -> str:
    """
    Extracts the album ID from an Apple Music URL.
    """
    url = normalize_apple_music_url(url)
    parsed = urlparse(url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    return parts[-1]


async def get_track_schema(url: str) -> List[TrackInputSchema]:
    """
    Fetches metadata for a single track and returns it as a list containing one TrackInputSchema.
    """
    url = normalize_apple_music_url(url)
    api = await get_api()
    song_id = extract_song_id_from_url(url)

    song = await api.get_song(song_id)
    data = song["data"][0]
    attrs = data["attributes"]
    album_id = data["relationships"]["albums"]["data"][0]["id"]
    
    href_parts = data.get("href", "").split("/")
    storefront = href_parts[3] if len(href_parts) > 3 else "us"

    return [
        TrackInputSchema(
            album_id=album_id,
            song_id=data["id"],
            title=attrs["name"],
            artist=attrs["artistName"],
            album=attrs.get("albumName", ""),
            url=attrs["url"],
            storefront=storefront,
            isrc=attrs.get("isrc"),
            artwork=get_artwork_url(attrs.get("artwork")),
            audio_traits=attrs.get("audioTraits", [])
        )
    ]


async def get_album_urls(url: str) -> List[TrackInputSchema]:
    """
    Fetches metadata for all tracks in an album.
    """
    url = normalize_apple_music_url(url)
    api = await get_api()

    info = AppleMusicInterface.get_url_info(url)
    album_id = info.id

    album = await api.get_album(album_id)
    album_node = album["data"][0]
    tracks = album["data"][0]["relationships"]["tracks"]["data"]

    href_parts = album_node.get("href", "").split("/")
    storefront = href_parts[3] if len(href_parts) > 3 else "us"

    lists_of_tracks: List[TrackInputSchema] = []

    for track in tracks:
        if track.get("type") != "songs":
            continue

        attrs = track["attributes"]
        lists_of_tracks.append(
            TrackInputSchema(
                album_id=album["data"][0]["id"],
                song_id=track["id"],
                title=attrs["name"],
                artist=attrs["artistName"],
                album=attrs.get("albumName", ""),
                url=album_url_to_song_url(attrs["url"]),
                storefront=storefront,
                isrc=attrs.get("isrc"),
                artwork=get_artwork_url(attrs.get("artwork")),
                audio_traits=attrs.get("audioTraits", [])
            )
        )

    return lists_of_tracks

async def get_artist_uls(url: str) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """

    Returns:
        List[Dict]:
    """
    url = normalize_apple_music_url(url)
    api = await get_api()

    info = AppleMusicInterface.get_url_info(url)
    artist_id = info.id

    artist = await api.get_artist(artist_id=artist_id)
    artist_data = artist["data"][0]

    selection = {
        "full-albums": [],
        'singles': [],
        'live-albums': [],
        'compilation-albums': [],
    }

    for section in selection:
        for album_item in artist_data['views'].get(section, {}).get("data", []):
            attrs = album_item["attributes"]
            album_dict = {
                "name": attrs["name"],
                "trackCount": attrs.get("trackCount"),
                "url": attrs.get("url"),
                "artwork": get_artwork_url(attrs.get("artwork")),
            }
            selection[section].append(album_dict)
    return (
        selection["full-albums"],
        selection["singles"],
        selection["live-albums"],
        selection["compilation-albums"],
    )



async def get_playlist_urls(url: str) -> List[TrackInputSchema]:
    """
    Fetches metadata for all tracks in a playlist.
    """
    url = normalize_apple_music_url(url)
    api = await get_api()

    info = AppleMusicInterface.get_url_info(url)
    playlist_id = info.id

    playlist = await api.get_playlist(playlist_id)
    playlist_node = playlist["data"][0]
    tracks = playlist["data"][0]["relationships"]["tracks"]["data"]

    href_parts = playlist_node.get("href", "").split("/")
    playlist_storefront = href_parts[3] if len(href_parts) > 3 else "us"

    lists_of_tracks: List[TrackInputSchema] = []

    for track in tracks:
        if track.get("type") != "songs":
            continue

        attrs = track["attributes"]
        track_url = attrs.get("url", "")

        if not track_url or "name" not in attrs:
            continue


        try:
            parsed_url = urlparse(track_url)
            path_parts = parsed_url.path.strip("/").split("/")
            album_id = path_parts[-1] if path_parts else ""
        except Exception:
            album_id = ""

        lists_of_tracks.append(
            TrackInputSchema(
                album_id=album_id,
                song_id=track["id"],
                title=attrs["name"],
                artist=attrs["artistName"],
                album=attrs.get("albumName", ""),
                url=album_url_to_song_url(attrs["url"]),
                storefront=playlist_storefront,
                isrc=attrs.get("isrc"),
                artwork=get_artwork_url(attrs.get("artwork")),
                audio_traits=attrs.get("audioTraits", [])
            )
        )

    return lists_of_tracks


async def get_music_video_schema(url: str) -> List[TrackInputSchema]:
    """
    Fetches metadata for a single Music Video and returns it as a list containing one TrackInputSchema.
    """
    url = normalize_apple_music_url(url)
    api = await get_api()
    info = AppleMusicInterface.get_url_info(url)
    mv_id = info.id

    try:
        mv = await api.get_music_video(mv_id)
        data = mv["data"][0]
        attrs = data["attributes"]
        href_parts = data.get("href", "").split("/")
        storefront = href_parts[3] if len(href_parts) > 3 else "us"

        return [
            TrackInputSchema(
                album_id=None,
                song_id=data["id"],
                title=attrs.get("name", "Music Video"),
                artist=attrs.get("artistName", ""),
                album=attrs.get("albumName", ""),
                url=attrs.get("url", url),
                storefront=storefront,
                isrc=attrs.get("isrc"),
                artwork=get_artwork_url(attrs.get("artwork")),
                audio_traits=attrs.get("audioTraits", [])
            )
        ]
    except Exception:
        return [
            TrackInputSchema(
                album_id=None,
                song_id=mv_id,
                title="Music Video",
                artist="Artist",
                album="",
                url=url,
                storefront="us",
                isrc=None,
                artwork=None,
                audio_traits=[]
            )
        ]


async def get_any_url(url: str) -> List[TrackInputSchema]:
    """
    Determines the URL type (song, album, playlist, or music-video) and fetches the corresponding metadata.
    """
    url = normalize_apple_music_url(url)
    info = AppleMusicInterface.get_url_info(url)

    if getattr(info, "type", "") in ("music-video", "video") or "music-video" in url:
        return await get_music_video_schema(url)

    if info.type == "album":
        if info.sub_id:
            return await get_track_schema(url)
        return await get_album_urls(url)

    if info.type == "playlist":
        return await get_playlist_urls(url)

    if info.type == "song":
        return await get_track_schema(url)

    raise ValueError(f"Unsupported URL type: {info.type}")



async def _main_test():
    """
    Runs a suite of tests to verify metadata fetching and shared API handling.
    """
    # url = "https://music.apple.com/us/song/wicked-games/1714908987"
    # print(f"Testing URL: {url}")
    #
    # # 1. Sequential calls in the same loop
    # test1 = await get_any_url(url)
    # print(f"Sequential call 1: Success (ISRC: {test1[0].isrc})")
    #
    # # 2. Concurrent calls in the same loop
    # results = await asyncio.gather(get_any_url(url), get_any_url(url))
    # print(f"Concurrent calls: Success (Count: {len(results)})")
    url = "https://music.apple.com/in/song/heart-to-heart/1452955723"
    test = await get_any_url(url)
    print(test)


if __name__ == "__main__":
    # Test 1: First asyncio.run call
    print("--- Event Loop 1 ---")
    asyncio.run(_main_test())
