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


def album_url_to_song_url(url: str) -> str:
    """
    Converts an Apple Music album URL with a song parameter to a direct song URL.
    """
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 3:
        return url

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
    info = AppleMusicInterface.get_url_info(url)
    storefront = info.storefront or "us"
    song_id = extract_song_id_from_url(url)

    try:
        song = await api._amp_request(f"v1/catalog/{storefront}/songs/{song_id}")
    except Exception:
        song = await api.get_song(song_id)

    if not song or "data" not in song or not song["data"]:
        raise ValueError(f"Song with ID {song_id} not found.")

    data = song["data"][0]
    attrs = data.get("attributes", {})
    albums_rel = data.get("relationships", {}).get("albums", {}).get("data", [])
    album_id = albums_rel[0]["id"] if albums_rel else ""

    href_parts = data.get("href", "").split("/")
    if len(href_parts) > 3:
        storefront = href_parts[3]

    return [
        TrackInputSchema(
            album_id=album_id,
            song_id=data.get("id", song_id),
            title=attrs.get("name", "Unknown Title"),
            artist=attrs.get("artistName", "Unknown Artist"),
            album=attrs.get("albumName", ""),
            url=attrs.get("url", url),
            storefront=storefront,
            isrc=attrs.get("isrc"),
            artwork=get_artwork_url(attrs.get("artwork"))
        )
    ]


async def get_album_urls(url: str) -> List[TrackInputSchema]:
    """
    Fetches metadata for all tracks in an album.
    """
    api = await get_api()
    info = AppleMusicInterface.get_url_info(url)
    storefront = info.storefront or "us"
    album_id = info.id

    try:
        album = await api._amp_request(f"v1/catalog/{storefront}/albums/{album_id}")
    except Exception:
        album = await api.get_album(album_id)

    if not album or "data" not in album or not album["data"]:
        raise ValueError(f"Album with ID {album_id} not found.")

    album_node = album["data"][0]
    tracks = album_node.get("relationships", {}).get("tracks", {}).get("data", [])

    href_parts = album_node.get("href", "").split("/")
    if len(href_parts) > 3:
        storefront = href_parts[3]

    lists_of_tracks: List[TrackInputSchema] = []

    for track in tracks:
        if track.get("type") != "songs":
            continue

        attrs = track.get("attributes", {})
        lists_of_tracks.append(
            TrackInputSchema(
                album_id=album_node.get("id", album_id),
                song_id=track.get("id"),
                title=attrs.get("name", "Unknown Track"),
                artist=attrs.get("artistName", "Unknown Artist"),
                album=attrs.get("albumName", ""),
                url=album_url_to_song_url(attrs.get("url", "")),
                storefront=storefront,
                isrc=attrs.get("isrc"),
                artwork=get_artwork_url(attrs.get("artwork"))
            )
        )

    return lists_of_tracks


async def get_artist_uls(url: str) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """
    Returns artist catalog grouped by category.
    """
    api = await get_api()
    info = AppleMusicInterface.get_url_info(url)
    storefront = info.storefront or "us"
    artist_id = info.id

    try:
        artist = await api._amp_request(
            f"v1/catalog/{storefront}/artists/{artist_id}",
            params={"views": "full-albums,singles,live-albums,compilation-albums"}
        )
    except Exception:
        artist = await api.get_artist(artist_id=artist_id)

    if not artist or "data" not in artist or not artist["data"]:
        raise ValueError(f"Artist with ID {artist_id} not found.")

    artist_data = artist["data"][0]

    selection = {
        "full-albums": [],
        'singles': [],
        'live-albums': [],
        'compilation-albums': [],
    }

    views = artist_data.get('views', {})
    for section in selection:
        for album_item in views.get(section, {}).get("data", []):
            attrs = album_item.get("attributes", {})
            album_dict = {
                "name": attrs.get("name", "Unknown Album"),
                "trackCount": attrs.get("trackCount"),
                "url": attrs.get("url", ""),
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
    api = await get_api()
    info = AppleMusicInterface.get_url_info(url)
    storefront = info.storefront or "us"
    playlist_id = info.id

    try:
        playlist = await api._amp_request(f"v1/catalog/{storefront}/playlists/{playlist_id}")
    except Exception:
        playlist = await api.get_playlist(playlist_id)

    if not playlist or "data" not in playlist or not playlist["data"]:
        raise ValueError(f"Playlist with ID {playlist_id} not found.")

    playlist_node = playlist["data"][0]
    tracks = playlist_node.get("relationships", {}).get("tracks", {}).get("data", [])

    href_parts = playlist_node.get("href", "").split("/")
    playlist_storefront = href_parts[3] if len(href_parts) > 3 else storefront

    lists_of_tracks: List[TrackInputSchema] = []

    for track in tracks:
        if track.get("type") != "songs":
            continue

        attrs = track.get("attributes", {})
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
                song_id=track.get("id"),
                title=attrs.get("name", "Unknown Track"),
                artist=attrs.get("artistName", "Unknown Artist"),
                album=attrs.get("albumName", ""),
                url=album_url_to_song_url(attrs.get("url", "")),
                storefront=playlist_storefront,
                isrc=attrs.get("isrc"),
                artwork=get_artwork_url(attrs.get("artwork")),
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
    url = "https://music.apple.com/us/album/so-be-it-remix/1676681781?i=1676681788"
    test = await get_any_url(url)
    print("TEST TRACK SCHEMA:", test)


if __name__ == "__main__":
    asyncio.run(_main_test())
