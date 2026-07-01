import asyncio
from urllib.parse import urlparse, parse_qs
from typing import Any
from gamdl.api import AppleMusicApi
from gamdl.interface import AppleMusicInterface



def album_url_to_song_url(url:str) -> str:
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")

    storefront = parts[0]  # in
    slug = parts[2]  # apocalypse

    query = parse_qs(parsed.query)
    song_id = query.get("i", [parts[-1]])[0]

    return f"https://music.apple.com/{storefront}/song/{slug}/{song_id}"



async def get_album_urls(url: str) -> list[Any]:
    api = await AppleMusicApi.create_from_netscape_cookies("./cookies.txt")

    info = AppleMusicInterface.get_url_info(url)
    album_id = info.id

    album = await api.get_album(album_id)
    tracks = album["data"][0]["relationships"]["tracks"]["data"]

    lists_of_tracks: list[Any] = []
    for track in tracks:
        lists_of_tracks.append(
            {
                "song_id": track["id"],
                "title": track["attributes"]["name"],
                "artist": track["attributes"]["artistName"],
                "album": track["attributes"]["albumName"],
                "url": album_url_to_song_url(track["attributes"]["url"])
            }
        )
    return lists_of_tracks


async def get_playlist_urls(url: str) -> list[Any]:
    api = await AppleMusicApi.create_from_netscape_cookies("./cookies.txt")

    info = AppleMusicInterface.get_url_info(url)
    album_id = info.id

    album = await api.get_playlist(album_id)
    tracks = album["data"][0]["relationships"]["tracks"]["data"]

    lists_of_tracks: list[Any] = []
    for track in tracks:
        lists_of_tracks.append(
            {
                "song_id": track["id"],
                "title": track["attributes"]["name"],
                "artist": track["attributes"]["artistName"],
                "album": track["attributes"]["albumName"],
                "url": album_url_to_song_url(track["attributes"]["url"])
            }
        )
    return lists_of_tracks


async def get_any_url(url: str) -> list[str] | str:
    info = AppleMusicInterface.get_url_info(url)

    if info.type == "album":
        return await get_album_urls(url)
    if info.type == "playlist":
        return await get_playlist_urls(url)
    if info.type == "song":
        return url
    raise ValueError(f"Unsupported URL type: {info.type}")


if __name__ == '__main__':
    asyncio.run(get_playlist_urls("https://music.apple.com/in/playlist/夢刃/pl.u-38oWZ6esZbL0EGY"))
    asyncio.run(get_album_urls("https://music.apple.com/in/album/everything-i-know-about-love/1641539616"))
    asyncio.run(get_any_url("https://music.apple.com/in/song/apocalypse/1217977755"))
