import asyncio
import sys
import os
from dotenv import load_dotenv

# Ensure event loop exists for Python 3.12+ / 3.14
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

load_dotenv()

from pyrogram import Client

async def test_message():
    api_id_str = os.getenv("API_ID", "").strip()
    api_hash = os.getenv("API_HASH", "").strip()
    token = os.getenv("TOKEN_API", "").strip()
    storage_channel = os.getenv("STORAGE_CHANNEL_ID", "-1004423011255").strip()

    # Allow custom chat_id and message_id from args
    chat_id = int(sys.argv[1]) if len(sys.argv) > 1 else int(storage_channel)
    message_id = int(sys.argv[2]) if len(sys.argv) > 2 else 2108

    print("=" * 60)
    print("       TELEGRAM CHANNEL MESSAGE DIAGNOSTIC SCRIPT")
    print("=" * 60)
    print(f"Target Chat ID:    {chat_id}")
    print(f"Target Message ID: {message_id}")
    print(f"Bot Token:         {token[:15]}...")
    print("-" * 60)

    if not token:
        print("ERROR: TOKEN_API is missing in .env!")
        return

    api_id = int(api_id_str) if api_id_str.isdigit() else 6
    api_hash = api_hash or "eb06694183e94d25944848a21645f372"

    client = Client(
        name="test_session",
        api_id=api_id,
        api_hash=api_hash,
        bot_token=token,
        in_memory=False,
    )

    try:
        await client.start()
        me = await client.get_me()
        print(f"SUCCESS: Logged in as Bot @{me.username} (ID: {me.id})")

        print(f"\n1. Testing client.get_chat({chat_id})...")
        try:
            chat = await client.get_chat(chat_id)
            print(f"   SUCCESS: Chat Title = '{chat.title}', Type = {chat.type}")
        except Exception as e:
            print(f"   FAILED: {type(e).__name__} -> {e}")

        print(f"\n2. Testing client.get_messages({chat_id}, {message_id})...")
        try:
            msg = await client.get_messages(chat_id, message_id)
            if not msg or msg.empty:
                print(f"   FAILED: Message {message_id} is EMPTY or DELETED!")
            else:
                media = msg.audio or msg.document or msg.video or msg.voice
                print(f"   SUCCESS: Found Message ID {msg.id}")
                if media:
                    print(f"   - Media Type: {type(media).__name__}")
                    print(f"   - File Name:  {getattr(media, 'file_name', 'N/A')}")
                    print(f"   - File Size:  {getattr(media, 'file_size', 0)} bytes")
                    print(f"   - File ID:    {getattr(media, 'file_id', 'N/A')[:30]}...")
                else:
                    print("   - Warning: Message exists but has no media file attached.")
        except Exception as e:
            print(f"   FAILED: {type(e).__name__} -> {e}")

    except Exception as e:
        print(f"CRITICAL ERROR: {type(e).__name__} -> {e}")
    finally:
        if client.is_connected:
            await client.stop()
        print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_message())
