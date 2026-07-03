Here is a clean, comprehensive reference report covering your entire setup—from the Cloudflare network layer down to the user authentication and file-streaming logic.

---

# Backend Architecture & File Streaming Blueprint

This document outlines the core technical architecture for securely pulling tracks from a local home database, authenticating users via Telegram, and streaming files up to 2GB directly through a web browser.

---

## 1. Network Layer (Cloudflare TCP Tunnel)

To securely bridge a local home database to a remote cloud script (like a GitHub Codespace) without opening public router ports, a raw **TCP Tunnel** is established using `cloudflared`.

### Infrastructure Setup

* **Home Server:** Runs the Cloudflare daemon, binding local database traffic (e.g., PostgreSQL on port `5432`) directly to a custom domain routing target:
```bash
cloudflared tunnel route dns <tunnel-name> db.yourdomain.com
cloudflared tunnel run --url tcp://localhost:5432 <tunnel-name>

```


* **Codespace Client:** Runs a loopback daemon to intercept the WebSocket-wrapped TCP data over the public web and map it to a local loopback port:
```bash
cloudflared access tcp --hostname db.yourdomain.com --url localhost:5432

```


* **Application Connection:** Code scripts safely communicate with the local loopback address:
```text
postgresql+asyncpg://user:password@localhost:5432/dbname

```



---

## 2. Web Authentication (Telegram Login Widget)

To identify users securely on the web interface without passwords, the system uses Telegram's native OpenID Connect widget.

### Setup Prerequisites

1. Open a chat with `@BotFather`.
2. Issue the `/setdomain` command.
3. Link your bot to your active web deployment domain (e.g., `[https://yourwebsite.com](https://yourwebsite.com)`).

### Frontend Integration

Place this widget block inside your HTML structure. It triggers a secure verification window and passes the authorized user details to your application logic:

```html
<script async 
        src="https://telegram.org/js/telegram-widget.js?24" 
        data-telegram-login="YOUR_BOT_USERNAME" 
        data-size="large" 
        data-onauth="onTelegramAuth(user)" 
        data-request-access="write">
</script>

<script>
  function onTelegramAuth(user) {
    // Forward the payload directly to the FastAPI authentication endpoint
    fetch('/auth/telegram', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(user)
    })
    .then(res => res.json())
    .then(data => console.log("Login verified:", data));
  }
</script>

```

### Backend Cryptographic Verification (FastAPI)

The backend prevents payload tampering by creating an HMAC signature using your private `BOT_TOKEN` as a cryptographic key, comparing it to the hash provided by Telegram:

```python
import hashlib
import hmac
from fastapi import FastAPI, HTTPException, Request

app = FastAPI()
BOT_TOKEN = "YOUR_BOT_TOKEN"

@app.post("/auth/telegram")
async def verify_telegram_login(request: Request):
    auth_data = await request.json()
    received_hash = auth_data.pop("hash", None)
    
    if not received_hash:
        raise HTTPException(status_code=400, detail="Missing validation hash.")

    # 1. Sort remaining properties alphabetically and format key=value strings separated by newlines
    data_check_string = "\n".join([f"{k}={v}" for k, v in sorted(auth_data.items()) if v is not None])
    
    # 2. Derive signature using SHA256 of the bot token
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    
    # 3. Securely compare hashes
    if not hmac.compare_digest(received_hash, expected_hash):
        raise HTTPException(status_code=401, detail="Invalid session signature.")
        
    return {"status": "authorized", "user_id": auth_data["id"]}

```

---

## 3. High-Capacity File Streaming (MTProto Integration)

Traditional Telegram Bot API calls enforce a hard **20MB download limit**. To serve audio tracks or albums up to **2GB** straight to a user's browser, the application utilizes the MTProto protocol via the `telethon` client wrapper.

### Core Processing Logic

1. **Database Lookup:** The user clicks a download link containing a unique track ID. FastAPI queries the database over the secure tunnel to fetch the corresponding Telegram `file_id`.
2. **Identifier Conversion:** Telethon's data utility takes the Bot API `file_id` string and parses it into an encrypted `InputDocument` object containing the underlying server coordinates (Data Center number, file numerical ID, and permission `access_hash`).
3. **Data Pipeline Execution:** Instead of buffering the file into memory or writing it to the web server's storage disk, a Python generator iteratively requests **64KB chunks** via Telethon's `iter_download` framework. FastAPI wraps this generator in a `StreamingResponse` to route the network chunks smoothly into the user's browser download pipe.

### Core Streaming Endpoint Pattern

```python
from fastapi.responses import StreamingResponse
from telethon import TelegramClient, utils

# Credentials acquired from https://my.telegram.org
client = TelegramClient("web_session", API_ID, API_HASH)

@app.get("/download/{song_id}")
async def download_track(song_id: str):
    # [1. Fetch 'track.file_id' from your local database record here]
    
    # 2. Decode the standard Bot API string to an MTProto structural coordinate object
    media_location = utils.resolve_bot_file_id(track.file_id)
    
    # 3. Define the asynchronous stream pipeline generator
    async def chunk_generator():
        async for chunk in client.iter_download(media_location, chunk_size=1024 * 64):
            yield chunk

    # 4. Stream chunks in real-time straight to the browser with explicit attachment headers
    return StreamingResponse(
        chunk_generator(),
        media_type="audio/mp4",
        headers={"Content-Disposition": f'attachment; filename="{track.title}.m4a"'}
    )

```

---

> ### 💡 System Advantages
> 
> 
> * **No Local Storage Costs:** Files act like liquid in a pipe; they stream out to the user instantly as they come in from Telegram, requiring zero megabytes of web-server disk space.
> * **Maximum File Scaling:** Completely removes the 20MB bot bottleneck, running smoothly on files up to 2GB.
> * **Secure Data Sourcing:** Your home storage database coordinates stay completely hidden behind Cloudflare's tunnel layer.
> 
>