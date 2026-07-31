import base64
import os
import struct
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import select
import httpx
from telethon import TelegramClient
from telethon.tl.types import InputDocumentFileLocation

from database import Tracks, async_session

# Load environment variables
load_dotenv()
TOKEN_API = os.getenv("TOKEN_API")
API_ID = int(os.getenv("TELEGRAM_API_ID", "32753567"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "323cb1bce88e8c2320c96e88db10786f")
LOCAL_SERVER_URL = os.getenv("LOCAL_SERVER_URL")

# Initialize Telethon Client for direct MTProto streaming (handles files > 50MB with zero limits)
clint = TelegramClient("bot_session", API_ID, API_HASH)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await clint.start(bot_token=TOKEN_API)
    print("Telethon client connected to Telegram MTProto.")
    yield
    await clint.disconnect()

app = FastAPI(lifespan=lifespan)

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

@app.get("/api/tracks")
async def get_tracks():
    async with async_session() as session:
        statement = select(Tracks).order_by(Tracks.isrc.desc()).limit(20)
        results = await session.exec(statement)
        tracks = results.all()
        return tracks

@app.get("/app/download/{file_id}")
async def stream_music(file_id: str):
    async with async_session() as session:
        statement = select(Tracks).where(Tracks.file_id == file_id)
        result = await session.exec(statement)
        track = result.first()
        if not track:
            raise HTTPException(status_code=404, detail="Track not found")

    async def file_sender():
        # 1. Primary Method: Fetch message via Telethon if chat_id & message_id are stored
        chat_id = getattr(track, "chat_id", None)
        message_id = getattr(track, "message_id", None)
        if chat_id and message_id:
            try:
                msg = await clint.get_messages(chat_id, ids=message_id)
                if msg and msg.media:
                    async for chunk in clint.iter_download(msg.media, chunk_size=128 * 1024):
                        yield chunk
                    return
            except Exception as e:
                print(f"Telethon get_messages direct stream failed: {e}")

        # 2. Secondary Method: Stream via unpacked MTProto location object
        file_loc = parse_bot_file_id(file_id)
        if file_loc:
            try:
                async for chunk in clint.iter_download(file_loc, chunk_size=128 * 1024):
                    yield chunk
                return
            except Exception as e:
                print(f"Telethon file_loc stream failed: {e}")

        # 3. Tertiary Fallback: HTTP Bot API getFile (works for small files or local Bot API server)
        server_url = LOCAL_SERVER_URL or "https://api.telegram.org"
        api_url = f"{server_url}/bot{TOKEN_API}/getFile?file_id={file_id}"
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(api_url)
                response.raise_for_status()
                data = response.json()
                if not data.get("ok"):
                    raise HTTPException(status_code=400, detail=f"Failed to get file info: {data.get('description')}")
                
                file_path = data["result"]["file_path"]
                download_url = f"{server_url}/file/bot{TOKEN_API}/{file_path}"
                
                async with client.stream("GET", download_url) as stream_resp:
                    stream_resp.raise_for_status()
                    async for chunk in stream_resp.aiter_bytes(chunk_size=128 * 1024):
                        yield chunk
            except Exception as e:
                print(f"All streaming fallbacks failed: {e}")
                raise HTTPException(status_code=500, detail="Failed to stream file from Telegram")

    filename = f"{track.artist} - {track.title}.m4a"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Accept-Ranges": "bytes"
    }

    return StreamingResponse(
        file_sender(),
        media_type="audio/mp4",
        headers=headers,
    )
