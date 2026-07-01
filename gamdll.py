import asyncio

from gamdl.api import AppleMusicApi
from gamdl.downloader import (
    AppleMusicBaseDownloader,
    AppleMusicDownloader,
    AppleMusicMusicVideoDownloader,
    AppleMusicSongDownloader,
    AppleMusicUploadedVideoDownloader,
)
from gamdl.interface import (
    AppleMusicBaseInterface,
    AppleMusicInterface,
    AppleMusicMusicVideoInterface,
    AppleMusicSongInterface,
    AppleMusicUploadedVideoInterface,
)


async def main():
    # Create AppleMusicApi instance from cookies
    apple_music_api = await AppleMusicApi.create_from_netscape_cookies(
        cookies_path="cookies.txt",
    )

    # Check subscription
    if not apple_music_api.active_subscription:
        print("No active Apple Music subscription")
        return

    # Create base interface
    base_interface = await AppleMusicBaseInterface.create(
        apple_music_api=apple_music_api,
    )

    # Create specialized interfaces
    song_interface = AppleMusicSongInterface(
        base=base_interface,
    )
    music_video_interface = AppleMusicMusicVideoInterface(
        base=base_interface,
    )
    uploaded_video_interface = AppleMusicUploadedVideoInterface(
        base=base_interface,
    )

    # Create main interface
    interface = AppleMusicInterface(
        song=song_interface,
        music_video=music_video_interface,
        uploaded_video=uploaded_video_interface,
    )

    # Create base downloader
    base_downloader = AppleMusicBaseDownloader(
        interface=interface,
    )

    # Create specialized downloaders
    song_downloader = AppleMusicSongDownloader(base=base_downloader)
    music_video_downloader = AppleMusicMusicVideoDownloader(
        base=base_downloader,
    )
    uploaded_video_downloader = AppleMusicUploadedVideoDownloader(base=base_downloader)

    # Create main downloader
    downloader = AppleMusicDownloader(
        song=song_downloader,
        music_video=music_video_downloader,
        uploaded_video=uploaded_video_downloader,
    )
    
    # Download from URL
    url = "https://music.apple.com/in/song/falling-behind/1641540030"

    download_queue = []
    async for media in downloader.get_download_item_from_url(url):
        download_queue.append(media)

    for download_item in download_queue:
        try:
            await downloader.download(download_item)
        except Exception as e:
            print(f"Error downloading: {e}")


if __name__ == "__main__":
    asyncio.run(main())