import base64
import os
import struct
from typing import Optional
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import select, func, or_
import httpx
from telethon import TelegramClient
from telethon.tl.types import InputDocumentFileLocation

from database import Tracks, async_session, init_db

# Load environment variables
load_dotenv()
TOKEN_API = os.getenv("TOKEN_API")
API_ID = int(os.getenv("TELEGRAM_API_ID", "32753567"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "323cb1bce88e8c2320c96e88db10786f")
LOCAL_SERVER_URL = os.getenv("LOCAL_SERVER_URL", "http://localhost:8081")

# Initialize Telethon Client for direct MTProto streaming (handles files > 50MB up to 2GB with zero limits)
clint = TelegramClient("bot_session", API_ID, API_HASH)

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_db()
        print("Database schema synchronized successfully.")
    except Exception as e:
        print(f"Database schema sync notice: {e}")
    await clint.start(bot_token=TOKEN_API)
    print("Telethon client connected to Telegram MTProto.")
    yield
    await clint.disconnect()

app = FastAPI(title="Apple Music Database & MTProto Stream Server", lifespan=lifespan)

# Enable CORS so local web pages (file:// or http://localhost) can communicate with backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def parse_bot_file_id(file_id: str) -> InputDocumentFileLocation:
    """
    Safely unpacks Telegram Bot API file_id into an MTProto location.
    """
    try:
        padded = file_id + '=' * (-len(file_id) % 4)
        decoded = base64.urlsafe_b64decode(padded)
        access_hash = struct.unpack("<q", decoded[-10:-2])[0]
        doc_id = struct.unpack("<q", decoded[-18:-10])[0]
        
        file_reference = b""
        if len(decoded) > 18:
            ref_len = decoded[14] if len(decoded) > 14 else 0
            if 15 + ref_len <= len(decoded) - 18:
                file_reference = decoded[15:15+ref_len]

        return InputDocumentFileLocation(
            id=doc_id,
            access_hash=access_hash,
            file_reference=file_reference,
            thumb_size=""
        )
    except Exception as e:
        print(f"Failed to parse file_id: {e}")
        return None

@app.get("/", response_class=FileResponse)
async def serve_index():
    """
    Serves the main am-l web dashboard index.html.
    """
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    index_path = os.path.join(root_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="index.html file not found in project root")

@app.get("/api/stats")
async def get_stats():
    """
    Returns total tracks, downloadable files count, unique artists and albums in local DB.
    """
    async with async_session() as session:
        total_tracks_res = await session.exec(select(func.count(Tracks.song_id)))
        total_tracks = total_tracks_res.one_or_none() or 0

        dl_tracks_res = await session.exec(select(func.count(Tracks.song_id)).where(Tracks.file_id.is_not(None)))
        dl_tracks = dl_tracks_res.one_or_none() or 0

        artists_res = await session.exec(select(func.count(func.distinct(Tracks.artist))))
        total_artists = artists_res.one_or_none() or 0

        albums_res = await session.exec(select(func.count(func.distinct(Tracks.album))))
        total_albums = albums_res.one_or_none() or 0

        return {
            "total_tracks": total_tracks,
            "downloadable_tracks": dl_tracks,
            "total_artists": total_artists,
            "total_albums": total_albums,
        }

@app.get("/api/tracks")
async def get_tracks(
    q: Optional[str] = Query(None, description="Search filter for title, artist, album or ISRC"),
    limit: int = Query(100, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    downloadable_only: bool = Query(False, description="Filter only tracks with active Telegram file_id")
):
    """
    Retrieves tracks from local PostgreSQL database with optional search filtering and pagination support.
    """
    async with async_session() as session:
        statement = select(Tracks)
        
        if downloadable_only:
            statement = statement.where(Tracks.file_id.is_not(None))
            
        if q:
            search_filter = or_(
                Tracks.title.ilike(f"%{q}%"),
                Tracks.artist.ilike(f"%{q}%"),
                Tracks.album.ilike(f"%{q}%"),
                Tracks.isrc.ilike(f"%{q}%")
            )
            statement = statement.where(search_filter)
        
        # Count total matching tracks
        count_stmt = select(func.count()).select_from(statement.subquery())
        total_res = await session.exec(count_stmt)
        total_count = total_res.one_or_none() or 0

        statement = statement.order_by(Tracks.title.asc()).offset(offset).limit(limit)
        results = await session.exec(statement)
        tracks = results.all()
        
        output = []
        for t in tracks:
            t_dict = t.model_dump() if hasattr(t, "model_dump") else t.dict()
            t_dict["has_file"] = bool(t.file_id)
            t_dict["download_url"] = f"/app/download/{t.file_id}" if t.file_id else None
            output.append(t_dict)

        return {
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "tracks": output
        }

@app.get("/app/download/{file_id}")
async def stream_music(file_id: str, dl: Optional[int] = Query(0, description="1 for attachment download, 0 for inline playback")):
    """
    Streams or downloads audio file from Telegram.
    Supports files > 20MB up to 2GB with zero limits via Telethon MTProto & Local Bot API.
    """
    async with async_session() as session:
        statement = select(Tracks).where(Tracks.file_id == file_id)
        result = await session.exec(statement)
        track = result.first()
        if not track:
            raise HTTPException(status_code=404, detail="Track not found in database")

    safe_title = (track.title or "track").replace('"', '').replace('\n', ' ')
    safe_artist = (track.artist or "artist").replace('"', '').replace('\n', ' ')
    filename = f"{safe_artist} - {safe_title}.m4a"
    disposition_type = "attachment" if dl == 1 else "inline"
    headers = {
        "Content-Disposition": f'{disposition_type}; filename="{filename}"',
        "Accept-Ranges": "bytes"
    }

    chat_id = getattr(track, "chat_id", None)
    message_id = getattr(track, "message_id", None)

    # Method 1: Telethon MTProto direct message stream (Handles files up to 2GB with ZERO size limit!)
    if chat_id and message_id:
        try:
            msg = await clint.get_messages(chat_id, ids=message_id)
            if msg and msg.media:
                async def mtproto_msg_sender():
                    try:
                        async for chunk in clint.iter_download(msg.media, chunk_size=256 * 1024):
                            yield chunk
                    except Exception as e:
                        print(f"Error streaming MTProto message media: {e}")

                return StreamingResponse(mtproto_msg_sender(), media_type="audio/mp4", headers=headers)
        except Exception as e:
            print(f"Telethon get_messages check failed: {e}")

    # Method 2: Local Docker Telegram Bot API Server (http://localhost:8081)
    server_url = (os.getenv("LOCAL_SERVER_URL") or "http://localhost:8081").rstrip('/')
    if server_url:
        try:
            api_url = f"{server_url}/bot{TOKEN_API}/getFile?file_id={file_id}"
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.get(api_url)
                if res.status_code == 200 and res.json().get("ok"):
                    file_info = res.json()["result"]
                    file_path = file_info["file_path"]
                    
                    # Direct local disk file response for maximum speed if file is accessible on host
                    if os.path.exists(file_path):
                        return FileResponse(file_path, filename=filename, media_type="audio/mp4", headers=headers)
                    
                    download_url = f"{server_url}/file/bot{TOKEN_API}/{file_path}"
                    async with client.get(download_url, timeout=15.0) as dl_check:
                        if dl_check.status_code == 200:
                            async def local_bot_api_sender():
                                async with httpx.AsyncClient(timeout=None) as stream_client:
                                    async with stream_client.stream("GET", download_url) as stream_resp:
                                        async for chunk in stream_resp.aiter_bytes(chunk_size=256 * 1024):
                                            yield chunk

                            return StreamingResponse(local_bot_api_sender(), media_type="audio/mp4", headers=headers)
        except Exception as e:
            print(f"Local Telegram Bot API check notice: {e}")

    # Method 3: Unpacked MTProto location fallback
    file_loc = parse_bot_file_id(file_id)
    if file_loc:
        try:
            async for _ in clint.iter_download(file_loc, offset=0, limit=1):
                async def mtproto_loc_sender():
                    try:
                        async for chunk in clint.iter_download(file_loc, chunk_size=256 * 1024):
                            yield chunk
                    except Exception as e:
                        print(f"Error streaming MTProto file_loc: {e}")

                return StreamingResponse(mtproto_loc_sender(), media_type="audio/mp4", headers=headers)
                break
        except Exception as e:
            print(f"MTProto file_loc validation failed (file reference expired): {e}")

    # Method 4: Cloud Telegram Bot API fallback (for files < 20MB)
    cloud_url = "https://api.telegram.org"
    try:
        api_url = f"{cloud_url}/bot{TOKEN_API}/getFile?file_id={file_id}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(api_url)
            if res.status_code == 200 and res.json().get("ok"):
                file_path = res.json()["result"]["file_path"]
                download_url = f"{cloud_url}/file/bot{TOKEN_API}/{file_path}"
                
                async def cloud_bot_api_sender():
                    async with httpx.AsyncClient(timeout=None) as stream_client:
                        async with stream_client.stream("GET", download_url) as stream_resp:
                            async for chunk in stream_resp.aiter_bytes(chunk_size=128 * 1024):
                                yield chunk

                return StreamingResponse(cloud_bot_api_sender(), media_type="audio/mp4", headers=headers)
    except Exception:
        pass

    raise HTTPException(
        status_code=410,
        detail="File reference expired on Telegram. Send or download this track once in your Telegram bot to refresh direct stream access."
    )
