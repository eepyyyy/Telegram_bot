import asyncio
from typing import Any
from gamdl.api import AppleMusicApi
from gamdl.interface import AppleMusicInterface


async def get_album_urls(url: str) -> list[Any]:

    api = await AppleMusicApi.create_from_netscape_cookies("./cookies.txt")

    info = AppleMusicInterface.get_url_info(url)
    album_id = info.id

    album = await api.get_album(album_id)
    tracks = album["data"][0]["relationships"]["tracks"]["data"]

    url_lists: list[Any] = [track["attributes"]['url']
                            for track in tracks
                            ]
    return url_lists
async def get_playlist_urls(url: str) -> list[Any]:

    api = await AppleMusicApi.create_from_netscape_cookies("./cookies.txt")

    info = AppleMusicInterface.get_url_info(url)
    playlist_id = info.id

    playlist = await api.get_playlist(playlist_id)
    tracks = playlist["data"][0]["relationships"]["tracks"]["data"]

    url_lists: list[Any] = [track["attributes"]['url']
                            for track in tracks
                            ]
    return url_lists

async def get_any_url(url: str) -> list[str]:
    info = AppleMusicInterface.get_url_info(url)

    if info.type == "album":
        return await get_album_urls(url)
    if info.type == "playlist":
        return await get_playlist_urls(url)
    if info.type == "song":
        return [url]
    raise ValueError(f"Unsupported URL type: {info.type}")


if __name__ == '__main__':
    asyncio.run(get_playlist_urls("https://music.apple.com/in/playlist/夢刃/pl.u-38oWZ6esZbL0EGY"))
    asyncio.run(get_album_urls("https://music.apple.com/in/album/everything-i-know-about-love/1641539616"))
    asyncio.run(get_any_url("https://music.apple.com/in/album/apocalypse/1217977525?i=1217977755"))
