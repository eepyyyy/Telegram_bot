import gamdlUrl
import asyncio

async def test():

    url = await gamdlUrl.get_any_url("https://music.apple.com/in/album/apocalypse/1217977755")
    process = await asyncio.create_subprocess_exec(
        "gamdl",
        *url
    )
    test = await process.wait()
    print(url)

asyncio.run(test())