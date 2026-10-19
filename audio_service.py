import asyncio
import os
import shutil
import structlog
from typing import AsyncGenerator, Awaitable, Callable, List, Optional

from gamdl.api import AppleMusicApi
from gamdl.downloader import (
    AppleMusicBaseDownloader,
    AppleMusicDownloader,
    AppleMusicMusicVideoDownloader,
    AppleMusicSongDownloader,
    AppleMusicUploadedVideoDownloader,
)
from gamdl.downloader.types import DownloadItem
from gamdl.interface import (
    AppleMusicBaseInterface,
    AppleMusicInterface,
    AppleMusicMusicVideoInterface,
    AppleMusicSongInterface,
    AppleMusicUploadedVideoInterface,
    GamdlInterfaceFormatNotAvailableError,
    GamdlInterfaceDecryptionNotAvailableError,
    GamdlInterfaceMediaNotStreamableError,
)
from gamdl.interface.enums import CoverFormat, SongCodec

logger = structlog.get_logger(__name__)

# Global singleton storage for the AppleMusicBaseInterface
_base_interface: Optional[AppleMusicBaseInterface] = None
_base_api: Optional[AppleMusicApi] = None
_base_lock: Optional[asyncio.Lock] = None
_base_loop: Optional[asyncio.AbstractEventLoop] = None
_cookies_mtime: Optional[float] = None
_cookies_resolved_path: Optional[str] = None


def get_codec_priority(format_type: str) -> List[SongCodec]:
    """Returns the SongCodec priority list for a given format string."""
    fmt = format_type.lower().strip()
    if fmt in ("aac", "aac-web"):
        return [SongCodec.AAC_WEB]
    elif fmt in ("atmos", "spatial"):
        return [SongCodec.ATMOS]
    elif fmt in ("lossless", "alac", "hi-res"):
        return [SongCodec.ALAC, SongCodec.AAC_WEB]
    else:
        # Default fallback
        return [SongCodec.ALAC, SongCodec.AAC_WEB]


def format_gamdl_error(err: Exception) -> str:
    """Translates internal gamdl and HTTP exceptions into user-friendly messages."""
    err_str = str(err)
    if "-1002" in err_str or "license exchange data" in err_str.lower():
        return (
            "Apple Music DRM license error (-1002): Playback license refused by Apple.\n\n"
            "Possible causes:\n"
            "1. The cookies.txt on the server has expired or has an inactive subscription.\n"
            "2. Another device/app is actively streaming on this Apple Music account (1 stream limit).\n"
            "3. The requested track or codec is restricted for web playback in this storefront."
        )
    if isinstance(err, GamdlInterfaceFormatNotAvailableError) or "format is not available" in err_str.lower():
        return "Requested audio format is not available for this track/album."
    if isinstance(err, GamdlInterfaceDecryptionNotAvailableError) or "decryption" in err_str.lower():
        return "Decryption key could not be obtained from Apple Music for this format. Try downloading in AAC."
    if isinstance(err, GamdlInterfaceMediaNotStreamableError) or "streamable" in err_str.lower():
        return "This track is not streamable in the current storefront."
    if "502" in err_str or "playback_dispatch_failed" in err_str or "1830087704" in err_str:
        return "Apple Music server error (502 Bad Gateway / Playback error). Please try again shortly."
    if "subscription" in err_str.lower() or "no active subscription" in err_str.lower():
        return "Apple Music subscription error (No Active Subscription). Please check or renew your cookies.txt."
    return f"Download failed: {err_str}"


def invalidate_base_interface() -> None:
    """Explicitly invalidates the cached in-memory base interface."""
    global _base_interface, _base_api, _cookies_mtime, _cookies_resolved_path
    _base_interface = None
    _base_api = None
    _cookies_mtime = None
    _cookies_resolved_path = None
    logger.info("AppleMusicBaseInterface cache invalidated.")


async def get_base_interface(cookies_path: str = "cookies.txt") -> AppleMusicBaseInterface:
    """
    Returns a shared, persistent AppleMusicBaseInterface instance.
    Initializes from cookies.txt and keeps authentication tokens in memory.
    Automatically reloads if cookies.txt modification time changes on disk.
    """
    global _base_interface, _base_api, _base_lock, _base_loop, _cookies_mtime, _cookies_resolved_path

    current_loop = asyncio.get_running_loop()
    resolved_cookies = os.path.abspath(cookies_path)
    current_mtime = os.path.getmtime(resolved_cookies) if os.path.exists(resolved_cookies) else None

    # Reset singleton if running on a new event loop, or if cookies file changed
    if (
        _base_loop != current_loop
        or _cookies_resolved_path != resolved_cookies
        or _cookies_mtime != current_mtime
    ):
        _base_interface = None
        _base_api = None
        _base_lock = asyncio.Lock()
        _base_loop = current_loop

    async with _base_lock:
        if _base_interface is None:
            if not os.path.exists(resolved_cookies):
                raise FileNotFoundError(f"Cookies file not found at: {resolved_cookies}")

            # Initialize AppleMusicApi from cookies
            _base_api = await AppleMusicApi.create_from_netscape_cookies(resolved_cookies)

            # Initialize base interface
            _base_interface = await AppleMusicBaseInterface.create(
                apple_music_api=_base_api,
                cover_format=CoverFormat.JPG,
                cover_size=5000,
            )
            _cookies_mtime = current_mtime
            _cookies_resolved_path = resolved_cookies
            logger.info("AppleMusicBaseInterface in-memory singleton successfully initialized.", cookies=resolved_cookies)

        return _base_interface


async def create_task_downloader(
    format_type: str,
    output_dir: str,
    temp_dir: str,
    cookies_path: str = "cookies.txt",
) -> AppleMusicDownloader:
    """
    Creates an AppleMusicDownloader instance configured for a specific task output
    directory and format, while sharing the persistent AppleMusicBaseInterface.
    """
    base_interface = await get_base_interface(cookies_path)
    codecs = get_codec_priority(format_type)

    song_interface = AppleMusicSongInterface(
        base=base_interface,
        codec_priority=codecs,
    )
    music_video_interface = AppleMusicMusicVideoInterface(base=base_interface)
    uploaded_video_interface = AppleMusicUploadedVideoInterface(base=base_interface)

    interface = AppleMusicInterface(
        song=song_interface,
        music_video=music_video_interface,
        uploaded_video=uploaded_video_interface,
    )

    base_downloader = AppleMusicBaseDownloader(
        interface=interface,
        output_path=output_dir,
        temp_path=temp_dir,
        truncate=80,
    )

    song_downloader = AppleMusicSongDownloader(base=base_downloader)
    music_video_downloader = AppleMusicMusicVideoDownloader(base=base_downloader)
    uploaded_video_downloader = AppleMusicUploadedVideoDownloader(base=base_downloader)

    downloader = AppleMusicDownloader(
        song=song_downloader,
        music_video=music_video_downloader,
        uploaded_video=uploaded_video_downloader,
        overwrite=True,
        save_cover=True,
    )

    return downloader


async def download_audio(
    urls: List[str],
    format_type: str,
    output_dir: str,
    temp_dir: str,
    cookies_path: str = "cookies.txt",
    on_track_done: Optional[Callable[[DownloadItem, str], Awaitable[None]]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> List[DownloadItem]:
    """
    Downloads audio tracks using the in-memory gamdl engine.
    Invokes on_track_done(item, final_path) as each track finishes downloading and tagging.
    """
    downloader = await create_task_downloader(
        format_type=format_type,
        output_dir=output_dir,
        temp_dir=temp_dir,
        cookies_path=cookies_path,
    )

    downloaded_items: List[DownloadItem] = []

    try:
        for url in urls:
            if is_cancelled and is_cancelled():
                logger.info("Download cancelled before processing URL", url=url)
                break

            async for item in downloader.get_download_item_from_url(url):
                if is_cancelled and is_cancelled():
                    logger.info("Download cancelled during item iteration", url=url)
                    break

                try:
                    # Download, decrypt, and apply tags
                    await downloader.download(item)
                    downloaded_items.append(item)

                    final_path = getattr(item, "final_path", None)
                    if on_track_done and final_path:
                        await on_track_done(item, str(final_path))
                except (GamdlInterfaceDecryptionNotAvailableError, Exception) as dl_err:
                    dl_err_str = str(dl_err).lower()
                    # If requesting lossless and ALAC decryption is unavailable (e.g. FairPlay-only without wrapper), auto fallback to AAC
                    if format_type.lower() in ("lossless", "alac") and (
                        isinstance(dl_err, GamdlInterfaceDecryptionNotAvailableError)
                        or "-1002" in dl_err_str
                        or "decryption is not available" in dl_err_str
                    ):
                        logger.warning("ALAC decryption unavailable for track; auto-falling back to AAC-web", url=url, error=str(dl_err))
                        aac_downloader = await create_task_downloader(
                            format_type="aac",
                            output_dir=output_dir,
                            temp_dir=temp_dir,
                            cookies_path=cookies_path,
                        )
                        async for aac_item in aac_downloader.get_download_item_from_url(url):
                            await aac_downloader.download(aac_item)
                            downloaded_items.append(aac_item)
                            final_path = getattr(aac_item, "final_path", None)
                            if on_track_done and final_path:
                                await on_track_done(aac_item, str(final_path))
                        continue
                    raise

    except Exception as e:
        err_str = str(e).lower()
        if "-1002" in err_str or "license exchange data" in err_str or "subscription" in err_str or "unauthorized" in err_str:
            logger.warning("License/auth error encountered; invalidating in-memory base interface", error=str(e))
            invalidate_base_interface()
        raise
    finally:
        # Cleanup temp directory if it exists
        if os.path.exists(temp_dir):
            try:
                await asyncio.to_thread(shutil.rmtree, temp_dir, ignore_errors=True)
            except Exception:
                pass

    return downloaded_items
