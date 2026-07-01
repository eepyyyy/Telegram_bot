from gamdlUrl import get_playlist_urls, get_album_urls, get_any_url
import asyncio

async def test():
    print(await get_playlist_urls("https://music.apple.com/in/playlist/夢刃/pl.u-38oWZ6esZbL0EGY"))
    print(await get_album_urls("https://music.apple.com/in/album/everything-i-know-about-love/1641539616"))
    print(await get_any_url("https://music.apple.com/in/song/apocalypse/1217977755"))

asyncio.run(test())