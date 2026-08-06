import asyncio
import logging
import re
import math
from typing import Optional, Tuple
from aiohttp import ClientError, web
from pyrogram import Client
from pyrogram.errors import FloodWait, RPCError
from pyrogram.types import Message
from server.client import get_pyrogram_client

logger = logging.getLogger("server.stream")

CHUNK_SIZE = 1024 * 1024  # 1 MB chunk size for fast Telegram MTProto downloading

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "Range, Content-Type, Authorization, *",
    "Access-Control-Expose-Headers": "Content-Length, Content-Range, Content-Disposition, Accept-Ranges",
}


def parse_range_header(range_header: Optional[str], total_size: int) -> Tuple[int, int, int]:
    """
    Parses HTTP Range header string into (start_byte, end_byte, length).
    """
    if not range_header or not range_header.startswith("bytes="):
        return 0, total_size - 1, total_size

    bytes_str = range_header.replace("bytes=", "").strip()
    parts = bytes_str.split("-")
    
    start_str = parts[0].strip()
    end_str = parts[1].strip() if len(parts) > 1 else ""

    if start_str and end_str:
        start = int(start_str)
        end = int(end_str)
    elif start_str:
        start = int(start_str)
        end = total_size - 1
    elif end_str:
        end = total_size - 1
        start = max(0, total_size - int(end_str))
    else:
        start = 0
        end = total_size - 1

    start = max(0, min(start, total_size - 1))
    end = max(start, min(end, total_size - 1))
    length = end - start + 1

    return start, end, length


def get_media_from_message(message: Message):
    """
    Extracts the media file metadata (file_size, mime_type, file_name) from Pyrogram Message.
    """
    media = message.audio or message.document or message.video or message.voice
    if not media:
        return None, 0, "application/octet-stream", "media_file"

    file_size = getattr(media, "file_size", 0)
    mime_type = getattr(media, "mime_type", "audio/flac") or "application/octet-stream"
    file_name = getattr(media, "file_name", None) or f"track_{message.id}.flac"

    return media, file_size, mime_type, file_name


async def fetch_message_with_retry(client: Client, chat_id: int, message_id: int) -> Message:
    """
    Fetches Telegram message with FloodWait retry handling.
    """
    while True:
        try:
            try:
                return await client.get_messages(chat_id, message_id)
            except Exception:
                logger.info(f"Resolving channel peer {chat_id} in Pyrogram cache...")
                await client.get_chat(chat_id)
                return await client.get_messages(chat_id, message_id)
        except FloodWait as e:
            logger.warning(f"FloodWait encountered: sleeping for {e.value} seconds...")
            await asyncio.sleep(e.value)
        except Exception as e:
            logger.error(f"Failed to fetch Telegram message {chat_id}/{message_id}: {e}")
            raise web.HTTPNotFound(text=f"Media message not found or channel inaccessible: {e}")


async def handle_telegram_stream(
    request: web.Request,
    chat_id: int,
    message_id: int,
    as_attachment: bool = False,
    override_filename: Optional[str] = None
) -> web.StreamResponse:
    """
    Direct MTProto Cloud Streamer for Telegram media messages.
    Supports files up to 2GB (or 4GB with Telegram Premium).
    Supports HTTP 206 Partial Content byte-range requests for seamless audio seeking.
    Zero disk usage - streams directly from Telegram cloud into client response buffer.
    """
    # Options request for CORS preflight
    if request.method == "OPTIONS":
        return web.Response(status=200, headers=CORS_HEADERS)

    client: Client = get_pyrogram_client()
    message: Message = await fetch_message_with_retry(client, chat_id, message_id)

    if not message or message.empty:
        raise web.HTTPNotFound(text="Telegram message is empty or deleted.")

    media, total_size, mime_type, default_name = get_media_from_message(message)
    if not media or total_size == 0:
        raise web.HTTPBadRequest(text="No valid audio/media file found in target message.")

    file_name = override_filename or default_name
    range_header = request.headers.get("Range")

    start_byte, end_byte, length = parse_range_header(range_header, total_size)
    is_partial = (range_header is not None)

    status_code = 206 if is_partial else 200
    disposition_type = "attachment" if as_attachment else "inline"

    headers = {
        **CORS_HEADERS,
        "Content-Type": mime_type,
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Disposition": f'{disposition_type}; filename="{file_name}"',
    }

    if is_partial:
        headers["Content-Range"] = f"bytes {start_byte}-{end_byte}/{total_size}"

    response = web.StreamResponse(status=status_code, headers=headers)
    await response.prepare(request)

    # HEAD request only returns headers
    if request.method == "HEAD":
        return response

    # Calculate Pyrogram chunk offsets
    start_chunk = start_byte // CHUNK_SIZE
    skip_first_bytes = start_byte % CHUNK_SIZE
    bytes_remaining = length

    while bytes_remaining > 0:
        try:
            async for chunk in client.stream_media(message, offset=start_chunk):
                if bytes_remaining <= 0:
                    break

                # Skip initial offset in first chunk
                if skip_first_bytes > 0:
                    chunk = chunk[skip_first_bytes:]
                    skip_first_bytes = 0

                # Trim trailing bytes if chunk exceeds remaining length
                if len(chunk) > bytes_remaining:
                    chunk = chunk[:bytes_remaining]

                await response.write(chunk)
                await response.drain()
                bytes_remaining -= len(chunk)
                start_chunk += 1
            break
        except FloodWait as e:
            logger.warning(f"FloodWait during stream_media: sleeping {e.value} seconds...")
            await asyncio.sleep(e.value)
        except (ClientError, ConnectionResetError, BrokenPipeError):
            logger.info(f"Client disconnected during stream of message {message_id}")
            break
        except Exception as e:
            logger.error(f"Error streaming message {message_id}: {e}")
            break

    return response
