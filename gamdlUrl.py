import asyncio
from typing import List, Optional, Dict
from urllib.parse import urlparse, parse_qs

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


def album_url_to_song_url(url: str) -> str:
    """
    Converts an Apple Music album URL with a song parameter to a direct song URL.
    """
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")

    storefront = parts[0]
    slug = parts[2]

    query = parse_qs(parsed.query)
    song_id = query.get("i", [parts[-1]])[0]

    return f"https://music.apple.com/{storefront}/song/{slug}/{song_id}"


def extract_song_id_from_url(url: str) -> str:
    """
    Extracts the song ID from an Apple Music URL.
    """
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    query = parse_qs(parsed.query)

    return query.get("i", [parts[-1]])[0]


def extract_album_id_from_url(url: str) -> str:
    """
    Extracts the album ID from an Apple Music URL.
    """
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    return parts[-1]


async def get_track_schema(url: str) -> List[TrackInputSchema]:
    """
    Fetches metadata for a single track and returns it as a list containing one TrackInputSchema.
    """
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
            isrc=attrs.get("isrc")
        )
    ]


async def get_album_urls(url: str) -> List[TrackInputSchema]:
    """
    Fetches metadata for all tracks in an album.
    """
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
                isrc=attrs.get("isrc")
            )
        )

    return lists_of_tracks

async def get_artist_uls(url: str) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """

    Returns:
        List[Dict]:
    """
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
                "artwork": attrs.get("artwork", {}).get("url"),
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
                isrc=attrs.get("isrc")
            )
        )

    return lists_of_tracks


async def get_any_url(url: str) -> List[TrackInputSchema]:
    """
    Determines the URL type (song, album, or playlist) and fetches the corresponding metadata.
    """
    info = AppleMusicInterface.get_url_info(url)

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
    url = "https://music.apple.com/us/artist/drake/271256"
    test = await get_artist_uls(url)
    print(test)


if __name__ == "__main__":
    # Test 1: First asyncio.run call
    print("--- Event Loop 1 ---")
    asyncio.run(_main_test())
