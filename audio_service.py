import asyncio
import os
import shutil
import structlog
from typing import AsyncGenerator, Awaitable, Callable, List, Optional

from gamdl.api import AppleMusicApi, WrapperApi
from gamdl.downloader import (
    AppleMusicBaseDownloader,
    AppleMusicDownloader,
    AppleMusicMusicVideoDownloader,
    AppleMusicSongDownloader,
    AppleMusicUploadedVideoDownloader,
)
from gamdl.downloader.enums import DownloadMode
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

# Monkey patch AppleMusicSongInterface._get_stream_info to handle Apple Music variant_id vs asset_metadata mismatch
_orig_get_stream_info = AppleMusicSongInterface._get_stream_info

async def _patched_get_stream_info(self, m3u8_master_url, codec):
    try:
        return await _orig_get_stream_info(self, m3u8_master_url, codec)
    except KeyError:
        import m3u8
        from gamdl.interface.types import StreamInfo, StreamInfoAv, MediaFileFormat
        from gamdl.interface.constants import MP4_FORMAT_CODECS
        m3u8_master_obj = m3u8.loads((await self.base.get_response(m3u8_master_url)).text)
        data = m3u8_master_obj.data
        playlist = self._get_playlist_from_codec(data, codec)
        if not playlist:
            return None
        stream_info = StreamInfo(use_single_content_key=False)
        stream_info.stream_url = f"{m3u8_master_url.rpartition('/')[0]}/{playlist['uri']}"
        stream_info.codec = playlist['stream_info']['codecs']
        is_mp4 = any(stream_info.codec.startswith(c) for c in MP4_FORMAT_CODECS)
        session_key_metadata = self._get_audio_session_key_metadata(data)
        if session_key_metadata:
            asset_metadata = self._get_asset_metadata(data) or {}
            audio_group = playlist['stream_info'].get('audio')
            target_asset = None
            for v in asset_metadata.values():
                if v.get('GROUP-ID') == audio_group or v.get('AUDIO-FORMAT-ID') == codec.value:
                    target_asset = v
                    break
            if target_asset and 'AUDIO-SESSION-KEY-IDS' in target_asset:
                drm_ids = target_asset['AUDIO-SESSION-KEY-IDS']
                stream_info.widevine_pssh = self._get_drm_uri_from_session_key(session_key_metadata, drm_ids, 'urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed')
                stream_info.playready_pssh = self._get_drm_uri_from_session_key(session_key_metadata, drm_ids, 'com.microsoft.playready')
                stream_info.fairplay_key = self._get_drm_uri_from_session_key(session_key_metadata, drm_ids, 'com.apple.streamingkeydelivery')
        return StreamInfoAv(audio_track=stream_info, file_format=MediaFileFormat.MP4 if is_mp4 else MediaFileFormat.M4A)

AppleMusicSongInterface._get_stream_info = _patched_get_stream_info

# Global singleton storage for the AppleMusicBaseInterface
_base_interface: Optional[AppleMusicBaseInterface] = None
_base_api: Optional[AppleMusicApi] = None
_base_lock: Optional[asyncio.Lock] = None
_base_loop: Optional[asyncio.AbstractEventLoop] = None
_cookies_mtime: Optional[float] = None
_cookies_resolved_path: Optional[str] = None


def get_wrapper_config() -> tuple[bool, Optional[str]]:
    """
    Checks environment variables, ~/.gamdl/config.ini, and local port 10020 for wrapper settings.
    Returns (use_wrapper: bool, wrapper_url: Optional[str]).
    """
    env_use_wrapper = os.getenv("USE_WRAPPER")
    env_wrapper_url = os.getenv("WRAPPER_URL")
    if env_use_wrapper is not None or env_wrapper_url is not None:
        use_w = env_use_wrapper.lower() in ("true", "1", "yes") if env_use_wrapper else bool(env_wrapper_url)
        return use_w, env_wrapper_url or "http://127.0.0.1:10020"

    try:
        from pathlib import Path
        import configparser
        candidates = [
            Path.home() / ".gamdl" / "config.ini",
            Path("/root/.gamdl/config.ini"),
            Path("/home/gana/.gamdl/config.ini"),
        ]
        for cfg_path in candidates:
            if cfg_path.exists():
                cp = configparser.ConfigParser(interpolation=None)
                cp.read(cfg_path, encoding="utf-8")
                if cp.has_section("gamdl"):
                    use_w = cp.getboolean("gamdl", "use_wrapper", fallback=False)
                    w_url = cp.get("gamdl", "wrapper_url", fallback=None)
                    if use_w:
                        return use_w, w_url or "http://127.0.0.1:10020"
    except Exception as e:
        logger.warning("Failed to read ~/.gamdl/config.ini", error=str(e))

    # Auto-detect if wrapper server is running locally on 127.0.0.1:10020
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.3)
        res = sock.connect_ex(('127.0.0.1', 10020))
        sock.close()
        if res == 0:
            logger.info("Auto-detected local Apple Music wrapper running on 127.0.0.1:10020")
            return True, "http://127.0.0.1:10020"
    except Exception:
        pass

    return False, None


def get_download_mode() -> DownloadMode:
    """
    Determines download mode (ytdlp or nm3u8dlre).
    Defaults to DownloadMode.YTDLP for bulletproof stability across platforms and Linux VPS.
    """
    mode_str = os.getenv("DOWNLOAD_MODE", "").lower().strip()
    if mode_str == "nm3u8dlre":
        return DownloadMode.NM3U8DLRE
    return DownloadMode.YTDLP


def get_codec_priority(format_type: str) -> List[SongCodec]:
    """Returns the SongCodec priority list for a given format string."""
    fmt = format_type.lower().strip()
    if fmt in ("aac", "aac-web"):
        return [SongCodec.AAC_WEB]
    elif fmt in ("atmos", "spatial"):
        return [SongCodec.ATMOS]
    elif fmt in ("lossless", "alac", "hi-res", "flac"):
        return [SongCodec.ALAC]
    else:
        return [SongCodec.ALAC]


def format_gamdl_error(err: Exception) -> str:
    """Translates internal gamdl and HTTP exceptions into user-friendly messages."""
    err_str = str(err)
    if "wrapper" in err_str.lower() or "502" in err_str:
        return f"Apple Music Wrapper error (required for ALAC/Atmos): {err_str}\nPlease verify wrapper service status or use /aac for 256kbps."
    if "-1002" in err_str or "license exchange data" in err_str.lower():
        return (
            "Apple Music DRM license error (-1002): Playback license refused by Apple.\n\n"
            "Possible causes:\n"
            "1. The cookies.txt on the server has expired or has an inactive subscription.\n"
            "2. Another device/app is actively streaming on this Apple Music account (1 stream limit).\n"
            "3. ALAC Lossless decryption requires an active Apple Music Wrapper."
        )
    if isinstance(err, GamdlInterfaceFormatNotAvailableError) or "format is not available" in err_str.lower():
        return "Requested audio format (ALAC Lossless) is not available for this track/album on Apple Music."
    if isinstance(err, GamdlInterfaceDecryptionNotAvailableError) or "decryption" in err_str.lower():
        return "Decryption key could not be obtained from Apple Music for ALAC Lossless. The wrapper service may be offline. Try /aac for AAC 256kbps."
    if isinstance(err, GamdlInterfaceMediaNotStreamableError) or "streamable" in err_str.lower():
        return "This track is not streamable in the current storefront."
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
    Supports both WrapperApi (for ALAC, Atmos, etc.) and netscape cookies.txt (AAC mode).
    Automatically reloads if cookies.txt modification time changes on disk.
    """
    global _base_interface, _base_api, _base_lock, _base_loop, _cookies_mtime, _cookies_resolved_path

    current_loop = asyncio.get_running_loop()
    resolved_cookies = os.path.abspath(cookies_path)
    current_mtime = os.path.getmtime(resolved_cookies) if os.path.exists(resolved_cookies) else None
    use_wrapper, wrapper_url = get_wrapper_config()

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
            wrapper_api = None
            if use_wrapper and wrapper_url:
                try:
                    logger.info("Initializing Apple Music WrapperApi", wrapper_url=wrapper_url)
                    wrapper_api = await WrapperApi.create(base_url=wrapper_url)
                    _base_api = await AppleMusicApi.create_from_wrapper(wrapper_api=wrapper_api)
                    logger.info("AppleMusicApi successfully initialized from wrapper.", wrapper_url=wrapper_url)
                except Exception as we:
                    logger.warning("Failed to initialize WrapperApi, falling back to cookies", error=str(we), wrapper_url=wrapper_url)
                    wrapper_api = None

            if wrapper_api is None:
                if not os.path.exists(resolved_cookies):
                    raise FileNotFoundError(f"Cookies file not found at: {resolved_cookies}")
                _base_api = await AppleMusicApi.create_from_netscape_cookies(resolved_cookies)

            # Initialize base interface
            _base_interface = await AppleMusicBaseInterface.create(
                apple_music_api=_base_api,
                wrapper_api=wrapper_api,
                cover_format=CoverFormat.JPG,
                cover_size=5000,
            )
            _cookies_mtime = current_mtime
            _cookies_resolved_path = resolved_cookies
            logger.info("AppleMusicBaseInterface in-memory singleton successfully initialized.", cookies=resolved_cookies, has_wrapper=bool(wrapper_api))

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
        download_mode=get_download_mode(),
        truncate=80,
    )

    original_download_stream = base_downloader.download_stream

    async def resilient_download_stream(stream_url: str, download_path: str):
        try:
            await original_download_stream(stream_url, download_path)
        except Exception as e:
            if base_downloader.download_mode != DownloadMode.YTDLP:
                logger.warning(
                    "Primary downloader failed, falling back to yt-dlp",
                    error=str(e),
                    stream_url=stream_url,
                )
                await base_downloader._download_ytdlp_async(stream_url, download_path)
            else:
                raise

    base_downloader.download_stream = resilient_download_stream

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
                except Exception as dl_err:
                    logger.error("Download or decryption failed for track", url=url, error=str(dl_err))
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
