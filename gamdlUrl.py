import asyncio
from urllib.parse import urlparse, parse_qs

from gamdl.api import AppleMusicApi
from gamdl.interface import AppleMusicInterface

from Schema import TrackInputSchema


def album_url_to_song_url(url: str) -> str:
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")

    storefront = parts[0]
    slug = parts[2]

    query = parse_qs(parsed.query)
    song_id = query.get("i", [parts[-1]])[0]

    return f"https://music.apple.com/{storefront}/song/{slug}/{song_id}"


def extract_song_id_from_url(url: str) -> str:
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    query = parse_qs(parsed.query)

    return query.get("i", [parts[-1]])[0]


def extract_album_id_from_url(url: str) -> str:
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")

    # The album ID is always the last segment of the URL path
    return parts[-1]

async def get_track_schema(url: str) -> list[TrackInputSchema]:
    """
    Takes an Apple Music track url and get single TrackInputSchema
    Args:
        url: "https://music.apple.com/in/song/night-light/1641540227"

    Returns:
        list[TrackInputSchema]:
        class TrackInputSchema(BaseModel):
            album_id: str | None = None
            album: str | None = None
            artist: str | None = None
            song_id: str | None = None
            title: str | None = None
            url: str | None = None
            file_id: str | None = None
            file_unique_id: str | None = None
    """
    api = await AppleMusicApi.create_from_netscape_cookies("./cookies.txt")

    song_id = extract_song_id_from_url(url)

    song = await api.get_song(song_id)
    data = song["data"][0]
    attrs = data["attributes"]
    album_id = data["relationships"]["albums"]["data"][0]["id"]
    # Safely extract storefront code from the track's API href segment
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


async def get_album_urls(url: str) -> list[TrackInputSchema]:
    """
        Takes an Apple Music track url and get List of TrackInputSchema of a Album
        Args:
            url: "https://music.apple.com/in/song/night-light/1641540227"

        Returns:
            list[TrackInputSchema]:
            class TrackInputSchema(BaseModel):
                album_id: str | None = None
                album: str | None = None
                artist: str | None = None
                song_id: str | None = None
                title: str | None = None
                url: str | None = None
                file_id: str | None = None
                file_unique_id: str | None = None
        """
    api = await AppleMusicApi.create_from_netscape_cookies("./cookies.txt")

    info = AppleMusicInterface.get_url_info(url)
    album_id = info.id

    album = await api.get_album(album_id)
    album_node = album["data"][0]
    tracks = album["data"][0]["relationships"]["tracks"]["data"]

    # Safely extract storefront code from the track's API href segment
    href_parts = album_node.get("href", "").split("/")
    storefront = href_parts[3] if len(href_parts) > 3 else "us"

    lists_of_tracks: list[TrackInputSchema] = []

    for track in tracks:
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


async def get_playlist_urls(url: str) -> list[TrackInputSchema]:
    """
    Takes an Apple Music track url and get List of TrackInputSchema of a playlist
    Args:
        url: "https://music.apple.com/in/song/night-light/1641540227"
    Returns:
        list[TrackInputSchema]:
        class TrackInputSchema(BaseModel):
            album_id: str | None = None
            album: str | None = None
            artist: str | None = None
            song_id: str | None = None
            title: str | None = None
            url: str | None = None
            file_id: str | None = None
            file_unique_id: str | None = None
    """
    api = await AppleMusicApi.create_from_netscape_cookies("./cookies.txt")

    info = AppleMusicInterface.get_url_info(url)
    playlist_id = info.id

    playlist = await api.get_playlist(playlist_id)
    playlist_node = playlist["data"][0]
    tracks = playlist["data"][0]["relationships"]["tracks"]["data"]

    # Safely extract storefront code from the track's API href segment
    href_parts = playlist_node.get("href", "").split("/")
    playlist_storefront = href_parts[3] if len(href_parts) > 3 else "us"

    lists_of_tracks: list[TrackInputSchema] = []

    for track in tracks:
        attrs = track["attributes"]
        track_url = attrs.get("url", "")

        if not track_url or "name" not in attrs:
            continue

        # --- EXTRACT ALBUM ID ---
        try:
            parsed_url = urlparse(track_url)
            path_parts = parsed_url.path.strip("/").split("/")

            album_id = path_parts[-1] if path_parts else ""
        except:
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


async def get_any_url(url: str) -> list[TrackInputSchema]:
    """
    Takes any type of Apple Music track url and get List of TrackInputSchema
    Args:
        url: example "https://music.apple.com/in/song/night-light/1641540227"
    Returns:
        list[TrackInputSchema]:
        class TrackInputSchema(BaseModel):
            album_id: str | None = None
            album: str | None = None
            artist: str | None = None
            song_id: str | None = None
            title: str | None = None
            url: str | None = None
            file_id: str | None = None
            file_unique_id: str | None = None
        If not Raise:
            ValueError(f"Unsupported URL type: {info.type}")
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


if __name__ == "__main__":
    test = asyncio.run(get_any_url("https://music.apple.com/us/song/wicked-games/1714908987"))

    print(test)