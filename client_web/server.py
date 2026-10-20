import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from aiohttp import web, ClientSession, ClientTimeout
import aiohttp

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Safe Windows stdout encoding
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from audio_service import create_task_downloader, get_base_interface
from gamdl.downloader.types import DownloadItem

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("client_web.server")

STATIC_DIR = Path(__file__).resolve().parent / "static"


def add_cors_headers(response: web.StreamResponse) -> web.StreamResponse:
    """Adds standard CORS headers to any response."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, HEAD"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Range, X-Requested-With"
    response.headers["Access-Control-Expose-Headers"] = "Content-Range, Content-Length, Accept-Ranges"
    return response


class ClientWebServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8090):
        self.host = host
        self.port = port
        self.app = web.Application(client_max_size=100 * 1024 * 1024)
        self.http_session: Optional[ClientSession] = None
        self._setup_routes()

    def _setup_routes(self):
        # UI routes
        self.app.router.add_get("/", self.handle_index)
        self.app.router.add_static("/static/", path=str(STATIC_DIR), name="static")

        # API routes
        self.app.router.add_route("OPTIONS", "/{tail:.*}", self.handle_options)
        self.app.router.add_post("/api/resolve", self.handle_resolve)
        self.app.router.add_get("/api/proxy", self.handle_proxy)
        self.app.router.add_get("/api/health", self.handle_health)

    async def handle_options(self, request: web.Request) -> web.Response:
        res = web.Response(status=204)
        return add_cors_headers(res)

    async def handle_index(self, request: web.Request) -> web.FileResponse:
        index_path = STATIC_DIR / "index.html"
        if not index_path.exists():
            return web.Response(text="index.html not found", status=404)
        return web.FileResponse(index_path)

    async def handle_health(self, request: web.Request) -> web.Response:
        cookies_exist = (PROJECT_ROOT / "cookies.txt").exists()
        res = web.json_response({
            "status": "online",
            "cookies_available": cookies_exist,
            "static_dir": str(STATIC_DIR),
            "client_decryption_enabled": True
        })
        return add_cors_headers(res)

    async def handle_resolve(self, request: web.Request) -> web.Response:
        """
        Resolves an Apple Music URL into track metadata, CDN stream URL, and decryption key.
        The server only acts as a key/metadata broker—the client performs stream download & decryption!
        """
        try:
            body = await request.json()
        except Exception:
            res = web.json_response({"success": False, "error": "Invalid JSON body"}, status=400)
            return add_cors_headers(res)

        url = body.get("url", "").strip()
        format_type = body.get("format", "aac").strip()

        if not url:
            res = web.json_response({"success": False, "error": "URL parameter is required"}, status=400)
            return add_cors_headers(res)

        logger.info(f"Resolving track for client-side decryption: {url} (format={format_type})")

        temp_dir = PROJECT_ROOT / "downloads" / "client_temp"
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            downloader = await create_task_downloader(
                format_type=format_type,
                output_dir=str(temp_dir),
                temp_dir=str(temp_dir),
                cookies_path=str(PROJECT_ROOT / "cookies.txt"),
            )

            resolved_item: Optional[DownloadItem] = None
            async for item in downloader.get_download_item_from_url(url):
                m = item.media
                if not m.partial and not m.error:
                    resolved_item = item
                    break

            if not resolved_item or not resolved_item.media:
                res = web.json_response({"success": False, "error": "Could not retrieve media metadata for track"}, status=404)
                return add_cors_headers(res)

            media = resolved_item.media
            audio_track = media.stream_info.audio_track if media.stream_info else None

            if not audio_track or not audio_track.stream_url:
                res = web.json_response({"success": False, "error": "No playable stream found for requested format"}, status=404)
                return add_cors_headers(res)

            # Retrieve decryption key
            kid_hex = None
            key_hex = None

            if media.decryption_key and hasattr(media.decryption_key, "audio_track") and media.decryption_key.audio_track:
                k_obj = media.decryption_key.audio_track
                kid_hex = getattr(k_obj, "kid", None)
                key_hex = getattr(k_obj, "key", None)
            elif audio_track.widevine_pssh:
                try:
                    base_itf = await get_base_interface(str(PROJECT_ROOT / "cookies.txt"))
                    k_obj = await base_itf.get_decryption_key(audio_track.widevine_pssh, media.media_id)
                    kid_hex = getattr(k_obj, "kid", None)
                    key_hex = getattr(k_obj, "key", None)
                except Exception as ke:
                    logger.warning(f"Key extraction warning for {media.media_id}: {ke}")

            # High-res cover URL
            cover_url = None
            if media.cover and getattr(media.cover, "url", None):
                cover_url = media.cover.url
            elif media.media_metadata and "attributes" in media.media_metadata:
                art = media.media_metadata["attributes"].get("artwork", {})
                if art and "url" in art:
                    cover_url = art["url"].replace("{w}", "1000").replace("{h}", "1000")

            tags = media.tags
            track_info = {
                "id": media.media_id,
                "title": tags.title if tags else media.media_metadata.get("attributes", {}).get("name", "Unknown Title"),
                "artist": tags.artist if tags else media.media_metadata.get("attributes", {}).get("artistName", "Unknown Artist"),
                "album": tags.album if tags else media.media_metadata.get("attributes", {}).get("albumName", "Unknown Album"),
                "album_artist": getattr(tags, "album_artist", None) if tags else None,
                "release_date": str(tags.date) if tags and tags.date else None,
                "genre": getattr(tags, "genre", None) if tags else None,
                "track_number": getattr(tags, "track", 1) if tags else 1,
                "total_tracks": getattr(tags, "track_total", 1) if tags else 1,
                "cover_url": cover_url,
                "duration_ms": media.media_metadata.get("attributes", {}).get("durationInMillis", 0),
                "stream_url": audio_track.stream_url,
                "proxy_stream_url": f"/api/proxy?url={audio_track.stream_url}",
                "codec": audio_track.codec.value if hasattr(audio_track.codec, "value") else str(audio_track.codec or "aac-web"),
                "drm_free": audio_track.drm_free,
                "use_cenc": audio_track.use_cenc,
                "kid": kid_hex,
                "key": key_hex,
                "pssh": audio_track.widevine_pssh,
            }

            res = web.json_response({
                "success": True,
                "track": track_info
            })
            return add_cors_headers(res)

        except Exception as e:
            logger.error(f"Error resolving track {url}: {e}", exc_info=True)
            res = web.json_response({"success": False, "error": str(e)}, status=500)
            return add_cors_headers(res)

    async def handle_proxy(self, request: web.Request) -> web.StreamResponse:
        """
        Streaming pass-through proxy with Range-header support.
        Ensures client-side fetch from Apple CDN will never be blocked by CORS in the browser.
        """
        target_url = request.query.get("url")
        if not target_url:
            return web.Response(text="Missing url parameter", status=400)

        if not self.http_session or self.http_session.closed:
            self.http_session = ClientSession(timeout=ClientTimeout(total=180))

        headers = {}
        if "Range" in request.headers:
            headers["Range"] = request.headers["Range"]

        try:
            async with self.http_session.get(target_url, headers=headers) as upstream:
                response = web.StreamResponse(
                    status=upstream.status,
                    reason=upstream.reason,
                    headers={
                        "Content-Type": upstream.headers.get("Content-Type", "application/octet-stream"),
                        "Content-Length": upstream.headers.get("Content-Length", ""),
                        "Accept-Ranges": "bytes",
                    }
                )
                if "Content-Range" in upstream.headers:
                    response.headers["Content-Range"] = upstream.headers["Content-Range"]

                add_cors_headers(response)
                await response.prepare(request)

                async for chunk in upstream.content.iter_chunked(64 * 1024):
                    await response.write(chunk)

                await response.write_eof()
                return response

        except Exception as e:
            logger.warning(f"Proxy error streaming {target_url}: {e}")
            return web.Response(text=f"Proxy error: {e}", status=502)

    async def start(self):
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        logger.info(f"Client-Side Decryption Web Server running at http://localhost:{self.port}")


def run_server(host="0.0.0.0", port=8090):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server = ClientWebServer(host=host, port=port)
    loop.run_until_complete(server.start())
    try:
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Server shutting down.")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8090))
    run_server(port=port)
