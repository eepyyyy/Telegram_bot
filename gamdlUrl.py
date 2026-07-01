import asyncio
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


async def get_track_schema(url: str) -> list[TrackSchema]:
    api = await AppleMusicApi.create_from_netscape_cookies("./cookies.txt")

    song_id = extract_song_id_from_url(url)

    song = await api.get_song(song_id)
    data = song["data"][0]
    attrs = data["attributes"]

    return [
        TrackSchema(
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

        lists_of_tracks.append(
            TrackSchema(
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
    asyncio.run(get_track_schema("https://music.apple.com/in/song/apocalypse/1217977755"))
