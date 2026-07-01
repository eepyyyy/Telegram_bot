import asyncio
from email.mime import text
from urllib.parse import urlparse, parse_qs

from gamdl.api import AppleMusicApi
from gamdl.interface import AppleMusicInterface
from Schema import TrackSchema


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

async def get_track_schema(url: str) -> list[TrackSchema]:
    api = await AppleMusicApi.create_from_netscape_cookies("./cookies.txt")

    song_id = extract_song_id_from_url(url)

    song = await api.get_song(song_id)
    data = song["data"][0]
    attrs = data["attributes"]
    album_id = data["relationships"]["albums"]["data"][0]["id"]

    return [
        TrackSchema(
            album_id=album_id,
            song_id=data["id"],
            title=attrs["name"],
            artist=attrs["artistName"],
            album=attrs.get("albumName", ""),
            url=attrs["url"],
        )
    ]


async def get_album_urls(url: str) -> list[TrackSchema]:
    api = await AppleMusicApi.create_from_netscape_cookies("./cookies.txt")

    info = AppleMusicInterface.get_url_info(url)
    album_id = info.id

    album = await api.get_album(album_id)
    tracks = album["data"][0]["relationships"]["tracks"]["data"]

    lists_of_tracks: list[TrackSchema] = []

    for track in tracks:
        attrs = track["attributes"]

        lists_of_tracks.append(
            TrackSchema(
                album_id=album["data"][0]["id"],
                song_id=track["id"],
                title=attrs["name"],
                artist=attrs["artistName"],
                album=attrs.get("albumName", ""),
                url=album_url_to_song_url(attrs["url"]),
            )
        )

    return lists_of_tracks


async def get_playlist_urls(url: str) -> list[TrackSchema]:
    api = await AppleMusicApi.create_from_netscape_cookies("./cookies.txt")

    info = AppleMusicInterface.get_url_info(url)
    playlist_id = info.id

    playlist = await api.get_playlist(playlist_id)
    tracks = playlist["data"][0]["relationships"]["tracks"]["data"]

    lists_of_tracks: list[TrackSchema] = []

    for track in tracks:
        attrs = track["attributes"]
        song_url = album_url_to_song_url(attrs["url"])

        print(get_album_id)
        lists_of_tracks.append(
            TrackSchema(
                album_id=extract_album_id_from_url(song_url),
                song_id=track["id"],
                title=attrs["name"],
                artist=attrs["artistName"],
                album=attrs.get("albumName", ""),
                url=album_url_to_song_url(attrs["url"]),
            )
        )

    return lists_of_tracks


async def get_any_url(url: str) -> list[TrackSchema]:
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
    test = asyncio.run(get_any_url("https://music.apple.com/in/playlist/夢刃/pl.u-38oWZ6esZbL0EGY"))

    print(test)