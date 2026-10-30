# 🎵 Apple Music Telegram Bot & Media Engine

<p align="center">
  <img src="logo/logo.png" alt="Apple Music Telegram Bot Logo" width="140" style="border-radius: 24px;" onerror="this.style.display='none'"/>
</p>

<p align="center">
  <b>High-performance asynchronous Telegram bot, background queue engine, and companion web stack for cataloguing, downloading, caching, and streaming Apple Music media.</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.0.0--stable-blue.svg?style=flat-square" alt="Version 1.0.0 Stable"/>
  <img src="https://img.shields.io/badge/python-3.14+-3776AB.svg?style=flat-square&logo=python&logoColor=white" alt="Python 3.14+"/>
  <img src="https://img.shields.io/badge/aiogram-3.29-2CA5E0.svg?style=flat-square&logo=telegram&logoColor=white" alt="Aiogram 3.29"/>
  <img src="https://img.shields.io/badge/database-PostgreSQL-4169E1.svg?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL"/>
  <img src="https://img.shields.io/badge/docker-ready-2496ED.svg?style=flat-square&logo=docker&logoColor=white" alt="Docker Ready"/>
  <img src="https://img.shields.io/badge/license-MIT-green.svg?style=flat-square" alt="License MIT"/>
</p>

---

## 🌟 Overview

**Apple Music Telegram Bot** is a production-grade Telegram bot and media service engineered for high-fidelity audio and video delivery. Built with **Python 3.14**, **Aiogram 3**, and **PostgreSQL (SQLModel/AsyncPG)**, it enables seamless downloading, persistent cloud caching, instant re-delivery, and HTTP byte-range audio streaming.

### Key Capabilities
- **Multi-Format Media Engine**: Native support for **ALAC (Lossless / Hi-Res)**, **Dolby Atmos (Spatial Audio E-AC3 JOC)**, **AAC 256kbps stereo**, and **Music Videos (H.265 / H.264 up to 4K/1080p)**.
- **Smart Cloud Caching**: Uploads media once to a private Telegram storage channel and indexes file metadata in PostgreSQL. Subsequent user requests deliver instantly from cache with 0 re-download overhead.
- **High-Speed Direct Link Fallback**: Oversized albums or archives exceeding Telegram file size limitations automatically upload to GoFile with one-click direct download links.
- **Cross-Platform Resolver**: Paste Spotify, YouTube, or Tidal links—the bot automatically resolves metadata and matches the corresponding Apple Music track for lossless acquisition.
- **Self-Healing Queue System**: In-memory task queues with per-user task serialization, configurable concurrency pools, graceful cancellation, and automatic deadlock cleanup.
- **HTTP Range Streaming Service**: Dedicated Pyrogram-backed streaming microservice allowing real-time seekable audio playback directly from Telegram cloud storage.
- **Admin Control Plane**: Built-in React + Vite web dashboard featuring live telemetry, queue monitors, manual track injection, album ZIP generation, and user quota controls.
- **Automated Operations**: Scheduled database backups with gzip compression, daily retention management, and zero-downtime containerized deployments.

---

## 📊 System Architecture & Charts

### 1. Overall System Architecture

```mermaid
flowchart TD
    subgraph Telegram_Network ["Telegram Ecosystem"]
        User(["👤 User / Client"])
        StorageChannel["📦 Private Telegram Storage Channel"]
    end

    subgraph Bot_Core ["Telegram Bot Core Engine"]
        WebhookReceiver["🌐 Webhook Receiver (FastHTTP)"]
        Dispatcher["⚡ Aiogram 3 Dispatcher"]
        CrossResolver["🔀 Cross-Platform Matcher (Spotify / YouTube / Tidal)"]
        
        subgraph Queue_Engine ["In-Memory Format Queues"]
            Q_ALAC["ALAC Lossless Queue"]
            Q_Atmos["Dolby Atmos Queue"]
            Q_AAC["AAC 256k Queue"]
            Q_MV["Music Video Queue"]
        end
    end

    subgraph Processing_Layer ["Media Processing Engine"]
        GamdlEngine["📥 gamdl / yt-dlp Core"]
        Remuxer["🎬 Bento4 & FFmpeg Pipeline"]
    end

    subgraph Data_Storage ["Data & Storage Tier"]
        Postgres[("🐘 PostgreSQL Database")]
        GoFile["☁️ GoFile High-Speed Fallback"]
    end

    subgraph Companion_Services ["Companion Services"]
        AdminUI["🖥️ Admin Dashboard (React / Vite)"]
        StreamServer["📻 HTTP Stream Server (Pyrogram)"]
    end

    User <-->|"Bot Commands & Links"| WebhookReceiver
    WebhookReceiver --> Dispatcher
    Dispatcher --> CrossResolver
    CrossResolver --> Queue_Engine
    
    Q_ALAC --> GamdlEngine
    Q_Atmos --> GamdlEngine
    Q_AAC --> GamdlEngine
    Q_MV --> GamdlEngine
    
    GamdlEngine --> Remuxer
    Remuxer -->|"Upload Media"| StorageChannel
    Remuxer -->|"Large Files (>2GB)"| GoFile
    StorageChannel -->|"Cache Message ID"| Postgres
    StorageChannel -->|"Forward / Copy Media"| User

    AdminUI <-->|"REST API + Telemetry"| Bot_Core
    StreamServer <-->|"Query Cached IDs"| Postgres
    StreamServer <-->|"Stream Audio Chunks"| StorageChannel
```

---

### 2. End-to-End Media Ingestion & Delivery Flow

```mermaid
sequenceDiagram
    autonumber
    actor User as "👤 User"
    participant Bot as "🤖 Bot Service"
    participant DB as "🐘 PostgreSQL"
    participant Queue as "📋 Format Queue"
    participant Worker as "⚙️ Worker Pool"
    participant Apple as "🍏 Apple Music API"
    participant Telegram as "📦 Telegram Channel"

    User->>Bot: Send Apple Music URL (or Spotify/YouTube link)
    Bot->>Bot: Normalize URL & Parse Flags (-n / --no-cache)
    
    alt Cache Hit (Instant Delivery)
        Bot->>DB: Query track by song_id / format
        DB-->>Bot: Return cached chat_id & message_id
        Bot->>Telegram: copy_message() to User
        Telegram-->>User: Instant Media Delivery (0s delay)
    else Cache Miss or -n Flag
        Bot->>Queue: Enqueue Task (Per-User Serialized Lock)
        Queue->>Worker: Dispatch Job to Free Worker
        Worker->>Apple: Fetch Metadata & Decryption Keys
        Worker->>Worker: Download Audio Streams (gamdl / yt-dlp)
        Worker->>Worker: Remux, Embed Cover Artwork & Tags (FFmpeg)
        Worker->>Telegram: Send to Storage Channel
        Telegram-->>Worker: Return message_id & file_id
        Worker->>DB: Save Track, File ID, Format & Size
        Worker->>Telegram: Forward / Copy to User Chat
        Telegram-->>User: Completed Media Delivered
    end
```

---

### 3. Task Queue State Machine & Self-Healing Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Idle

    Idle --> Queued: User Submits URL
    Queued --> Active: Worker Slot Available
    
    state Active {
        [*] --> FetchingMetadata
        FetchingMetadata --> Downloading: Keys & Stream Acquired
        Downloading --> Remuxing: Streams Complete
        Remuxing --> Uploading: Tags & Artwork Applied
        Uploading --> [*]: Sent to Telegram / GoFile
    }

    Active --> Completed: Success & Cached
    Active --> Failed: Exception or Error
    Active --> Cancelled: User / Admin Cancelled
    Active --> SelfHealed: Inactivity Timeout (15m+)

    Completed --> Idle: Release User Lock
    Failed --> Idle: Notify User & Release Lock
    Cancelled --> Idle: Clean Temp Files & Release Lock
    SelfHealed --> Idle: Reset Flags & Evict Stale Task
```

---

### 4. Cross-Platform Matcher Flow

```mermaid
flowchart LR
    A["External Link<br/>(Spotify / YouTube / Tidal)"] --> B{"URL Parser"}
    B -->|"Spotify"| C["Extract Track/Artist/ISRC"]
    B -->|"YouTube"| D["Extract Video Title & Channel"]
    B -->|"Tidal"| E["Extract Title & Artist"]
    
    C --> F["Apple Music Storefront Search API"]
    D --> F
    E --> F
    
    F --> G{"Match Found?"}
    G -->|"Yes"| H["Resolve Canonical Apple Music ID"]
    G -->|"No"| I["Report Not Found to User"]
    H --> J["Trigger Lossless Download Pipeline"]
```

---

## 🗄️ Database Architecture & Schema

The persistent layer is built on **PostgreSQL** using **SQLModel** (SQLAlchemy + Pydantic async ORM) with high-performance connection pooling via `asyncpg`.

### Entity-Relationship Diagram

```mermaid
erDiagram
    ALBUMS ||--o{ TRACKS : "contains (1:N)"
    ALBUMS ||--o{ AAC_TRACKS : "contains (1:N)"
    ALBUMS ||--o{ ATMOS_TRACKS : "contains (1:N)"
    USER ||--o{ DOWNLOAD_HISTORY : "logs (1:N)"

    ALBUMS {
        string album_id PK "Unique Apple Music album identifier"
        string artist "Artist display name"
        string album "Album title"
        string artwork "Cover artwork URL"
        string alac_zip_file_id "Telegram file_id for ALAC ZIP"
        string aac_zip_file_id "Telegram file_id for AAC ZIP"
        string atmos_zip_file_id "Telegram file_id for Atmos ZIP"
        string alac_gofile_url "High-speed GoFile URL (ALAC)"
        string aac_gofile_url "High-speed GoFile URL (AAC)"
        string atmos_gofile_url "High-speed GoFile URL (Atmos)"
        bigint alac_zip_size "File size in bytes"
        bigint aac_zip_size "File size in bytes"
        bigint atmos_zip_size "File size in bytes"
    }

    TRACKS {
        string song_id PK "Unique Apple Music song identifier"
        string album_id FK "References albums.album_id"
        string file_id "Telegram document file_id"
        string file_unique_id "Telegram unique file identifier"
        string title "Song title"
        string album "Album name"
        string artist "Artist name"
        string url "Canonical Apple Music URL"
        bigint size "File size in bytes"
        string storefront "Apple Music storefront (e.g. us, jp)"
        string isrc "International Standard Recording Code"
        string artwork "High-resolution artwork URL"
        bigint chat_id "Storage channel ID"
        integer message_id "Telegram storage message ID"
        datetime updated_at "Timestamp of last cache update"
    }

    AAC_TRACKS {
        string song_id PK "Unique Apple Music song identifier"
        string album_id FK "References albums.album_id"
        string file_id "Telegram document file_id"
        string file_unique_id "Telegram unique file identifier"
        string title "Song title"
        string album "Album name"
        string artist "Artist name"
        string url "Canonical Apple Music URL"
        bigint size "File size in bytes"
        string storefront "Apple Music storefront"
        string isrc "ISRC identifier"
        string artwork "Artwork URL"
        bigint chat_id "Storage channel ID"
        integer message_id "Telegram storage message ID"
        datetime updated_at "Timestamp of last cache update"
    }

    ATMOS_TRACKS {
        string song_id PK "Unique Apple Music song identifier"
        string album_id FK "References albums.album_id"
        string file_id "Telegram document file_id"
        string file_unique_id "Telegram unique file identifier"
        string title "Song title"
        string album "Album name"
        string artist "Artist name"
        string url "Canonical Apple Music URL"
        bigint size "File size in bytes"
        string storefront "Apple Music storefront"
        string isrc "ISRC identifier"
        string artwork "Artwork URL"
        bigint chat_id "Storage channel ID"
        integer message_id "Telegram storage message ID"
        datetime updated_at "Timestamp of last cache update"
    }

    MV_TRACKS {
        string song_id PK "Unique Apple Music video identifier"
        string album_id "Associated album identifier"
        string file_id "Telegram document file_id"
        string file_unique_id "Telegram unique file identifier"
        string title "Video title"
        string album "Album name"
        string artist "Artist name"
        string url "Canonical Apple Music URL"
        bigint size "File size in bytes"
        string storefront "Apple Music storefront"
        string isrc "ISRC identifier"
        string artwork "Artwork URL"
        bigint chat_id "Storage channel ID"
        integer message_id "Telegram storage message ID"
        string resolution "Video resolution (e.g. 1080p, 4k)"
        string codec "Video codec (e.g. h265, h264)"
        string gofile_url "Direct GoFile fallback link"
        datetime updated_at "Timestamp of last cache update"
    }

    USER {
        bigint user_id PK "Telegram User ID"
        boolean is_premium "VIP/Premium access flag"
        integer daily_limit "Max daily allowed downloads"
        integer downloaded_today "Count of downloads today"
        date last_download "Date of last recorded download"
        integer download_count "Total lifetime downloads"
        string preferred_format "Default audio format preference"
    }

    DOWNLOAD_HISTORY {
        integer id PK "Primary auto-incrementing key"
        bigint user_id FK "Telegram User ID"
        string song_id "Downloaded song identifier"
        string format_type "Format type (alac, aac, atmos, mv)"
        datetime downloaded_at "Timestamp of download request"
    }
```

### Table Breakdown

| Table | Model Class | Primary Purpose | Key Fields |
| :--- | :--- | :--- | :--- |
| `albums` | `Albums` | Album metadata, artwork, and full-discography ZIP cache | `album_id`, `alac_zip_file_id`, `alac_gofile_url`, `alac_zip_size` |
| `tracks` | `Tracks` | Hi-Res Lossless / ALAC individual track cache | `song_id`, `album_id`, `file_id`, `chat_id`, `message_id`, `size` |
| `aac_tracks` | `AACTracks` | High-efficiency AAC 256kbps audio track cache | `song_id`, `album_id`, `file_id`, `chat_id`, `message_id`, `size` |
| `atmos_tracks` | `AtmosTracks`| Dolby Atmos spatial audio track cache | `song_id`, `album_id`, `file_id`, `chat_id`, `message_id`, `size` |
| `mv_tracks` | `MVTracks` | Full HD / 4K music video cache | `song_id`, `resolution`, `codec`, `gofile_url`, `file_id` |
| `user` | `User` | User authorization, premium flags, and daily quotas | `user_id`, `is_premium`, `daily_limit`, `downloaded_today` |
| `download_history` | `DownloadHistory`| Audit log of all completed user downloads | `id`, `user_id`, `song_id`, `format_type`, `downloaded_at` |

---

### 📬 Database Access & Snapshots via Email

The PostgreSQL database houses a continuously growing archive of verified Apple Music metadata, artwork references, and indexed Telegram media files across ALAC, AAC, Dolby Atmos, and Music Video formats.

If you are a developer, researcher, or archivist interested in accessing our indexed database, obtaining a sanitized database dump (`.sql.gz`), or collaborating on media cataloguing:

> **📨 Request Database Access via Email:**
> - **Primary Contact:** [eepyyeepyyeepyy@gmail.com](mailto:eepyyeepyyeepyy@gmail.com)
> - **Secondary Contact:** [ganakarsha@gmail.com](mailto:ganakarsha@gmail.com)
> 
> *Please include your project name, intended use case, or environment details in your message. Database dumps or read-only connection credentials can be provided upon request.*

---

## 🎛️ Media Format Capabilities

| Format | Command | Resolution / Bitrate | Codec / Container | Best For |
| :--- | :--- | :--- | :--- | :--- |
| **ALAC Lossless** | Direct Link / `/lossless` | Up to 24-bit / 192 kHz | ALAC (`.m4a`) | Audiophiles, studio monitors, DACs |
| **Dolby Atmos** | `/atmos <url>` | Spatial Audio (5.1 / 7.1 JOC) | E-AC3 JOC (`.m4a`) | Headphones, multi-channel sound systems |
| **AAC Stereo** | `/aac <url>` | 256 kbps CBR | AAC LC (`.m4a`) | Mobile listening, lightweight file sizes |
| **Music Video** | `/mv <url>` | 1080p / 4K UHD | H.265 / H.264 (`.mp4`) | Full high-definition music video visuals |
| **Album ZIP** | Automatically packaged | Full Album Archive | `.zip` (Telegram / GoFile) | Complete discographies and batch playback |

---

## 📂 Repository Layout

The codebase is organized cleanly into modular components, background worker services, companion web microservices, and dedicated test/script suites:

```text
.
├── index.py                   # Bot entrypoint, webhook listener, worker managers, admin server
├── aac.py                     # High-efficiency AAC audio downloader and worker pool
├── atmos.py                   # Dolby Atmos spatial audio downloader and worker pool
├── lossless.py                # ALAC Hi-Res lossless audio downloader and worker pool
├── mv.py                      # Music video extraction and packaging worker pool
├── audio_service.py           # Shared metadata extraction, tagging, and track formatting
├── utils.py                   # Telegram upload helpers, caption protection, and GoFile fallback
├── queues.py                  # In-memory queue data structures, per-user locks, active state
├── bot_control.py             # Administrative pause/resume flags, worker concurrency registry
├── admin_routes.py            # Authenticated REST API endpoints for the dashboard
├── database.py                # SQLModel database engine and session factories
├── crud.py                    # Database queries for tracks, albums, users, and telemetry
├── schema.py                  # SQLModel schemas and database table definitions
├── gamdlUrl.py                # Apple Music URL normalization and metadata parsing
├── gamdlHelpUrl.py            # Detailed track/album inspection handlers
├── help.py                    # User command handlers, interactive menus, and help messages
├── artist.py                  # Artist discography browser and batch selection UI
│
├── dashboard/                 # React 18 + Vite + Tailwind administrator dashboard
├── server/                    # Standalone Pyrogram MTProto HTTP range streaming microservice
├── web/                       # Alternative local web downloader service
│
├── scripts/                   # Database maintenance, migrations, and operations
│   ├── backup_db.py           # Automated and manual PostgreSQL backup utility
│   ├── migrate_to_channel.py  # Media migration to private Telegram storage channel
│   ├── backfill_zip_sizes.py  # Historical ZIP file size calculator & backfill
│   └── update_artworks.py     # High-resolution artwork metadata backfill tool
│
├── tests/                     # Unit, integration, and stress test suites
│   ├── test_practical_queue.py# Realistic queue lifecycle & failure simulation test
│   ├── test_stress_queue.py   # High-concurrency load and race-condition test
│   └── test_channel_message.py# Telegram storage channel verification test
│
├── docker-compose.yml         # Containerized production multi-service deployment
├── Dockerfile                 # Multi-stage production container image
├── pyproject.toml             # Python 3.14 dependencies and project manifest
├── LICENSE                    # MIT Open Source License
└── .env.example               # Environment variable blueprint
```

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.14+** (configured in `pyproject.toml`) or **Docker & Docker Compose**
- **PostgreSQL 15+**
- **FFmpeg** and **Bento4** (installed and added to `PATH` for remuxing and MP4 decryption)
- **Node.js 18+** & npm (only required if building the admin dashboard from source)
- **Telegram Bot Token** (from [@BotFather](https://t.me/BotFather))
- **Telegram API ID & API Hash** (from [my.telegram.org](https://my.telegram.org) for Pyrogram streaming)
- Authorized Netscape-format Apple Music cookie file saved at `cookies.txt` (kept local, excluded from Git)

---

### Quick Start with Docker (Recommended)

1. **Clone the repository**:
   ```bash
   git clone https://github.com/eepyyyy/Telegram_bot.git
   cd Telegram_bot
   ```

2. **Configure your environment**:
   ```bash
   cp .env.example .env
   nano .env
   ```

3. **Place your Apple Music cookies**:
   Save your valid Netscape cookies file as `cookies.txt` in the root directory.

4. **Launch services**:
   ```bash
   docker compose up -d --build
   ```

5. **Verify service status**:
   ```bash
   docker compose logs -f tbot
   ```

---

### Manual Installation with `uv`

1. **Sync dependencies**:
   ```bash
   uv sync
   ```

2. **Build the Admin Dashboard**:
   ```bash
   cd dashboard
   npm install
   npm run build
   cd ..
   ```

3. **Start the Bot Service**:
   ```bash
   uv run python index.py
   ```

4. **(Optional) Start the MTProto HTTP Streaming Microservice**:
   ```bash
   uv run python -m server.main
   ```

---

## ⚙️ Configuration Reference (`.env`)

| Variable | Description | Default / Example |
| :--- | :--- | :--- |
| `TOKEN_API` | Telegram Bot Token from BotFather | `123456789:ABCdefGHI...` |
| `API_ID` / `API_HASH` | Telegram MTProto API credentials | `12345678` / `abcdef...` |
| `LOCAL_SERVER_URL` | Local Telegram Bot API server endpoint (optional) | `http://telegram-bot-api:8081` |
| `WEBHOOK_HOST` | Publicly reachable HTTPS domain for webhooks | `https://bot.example.com` |
| `WEBHOOK_PATH` | Path where webhook updates are delivered | `/webhook` |
| `WEBHOOK_SECRET` | Secret token verified against Telegram headers | `super_secret_token` |
| `WEBHOOK_LISTEN_HOST` | Host IP address for local webhook listener | `0.0.0.0` |
| `WEBHOOK_LISTEN_PORT` | Port for local webhook listener | `8080` |
| `STORAGE_CHANNEL_ID` | Telegram Channel ID used for persistent cloud caching | `-1001234567890` |
| `STREAM_SERVER_URL` | Public base URL for the HTTP audio streaming service | `https://stream.example.com` |
| `DATABASE_URL` | PostgreSQL async connection string | `postgresql+asyncpg://user:pass@host:5432/db` |
| `ADMIN_PASSWORD` | Administrator dashboard login password | Strong unique password |
| `JWT_SECRET` | Secret key used to sign dashboard JWT sessions | 64-char random hex string |
| `WORKER_CONCURRENCY` | Default concurrency limit for format workers | `2` |
| `AAC_WORKER_CONCURRENCY` | Concurrency limit for AAC workers | `3` |
| `ATMOS_WORKER_CONCURRENCY`| Concurrency limit for Dolby Atmos workers | `3` |
| `GOFILE_TOKEN` | Optional GoFile API token for high-speed fallback | Direct upload token |
| `DOWNLOAD_MODE` | Audio stream engine mode | `ytdlp` (or `nm3u8dlre`) |

---

## 💬 Bot Commands & Usage

- **Direct Link**: Send any Apple Music URL directly to download in **Lossless ALAC** (or fetch instantly from cache).
- **Direct Link with `-n`**: Append `-n` (e.g. `https://music.apple.com/... -n`) to bypass cache and download freshly.
- `/aac <url>`: Download audio in high-efficiency **AAC 256kbps**.
- `/atmos <url>`: Download audio in **Dolby Atmos Spatial Audio**.
- `/mv <url>`: Download music video in **Full HD / 4K**.
- `/artist <url>`: Browse artist discography, filter singles/albums, and trigger downloads interactively.
- `/info`: View personal statistics, downloaded tracks, format breakdown, and quota status.
- `/help`: Display interactive help menus, format guides, and syntax reference.
- **Cross-Platform Links**: Send any Spotify, Tidal, or YouTube URL directly. The resolver automatically maps the metadata to Apple Music and delivers lossless audio.

---

## 🛡️ Security & Best Practices

- **Never Commit Secrets**: Ensure `.env`, `cookies.txt`, `*.session`, and database dumps remain untracked in Git.
- **Reverse Proxy Protection**: Run the bot webhook and admin dashboard behind a reverse proxy (e.g., Cloudflare, NGINX, or Caddy) with SSL/TLS termination.
- **Webhook Token Authentication**: Always configure `WEBHOOK_SECRET` to prevent unauthorized requests from spoofing Telegram updates.
- **Least Privilege Database**: Ensure PostgreSQL uses a dedicated user with access restricted solely to the application database.

---

## 📄 License

This project is released under the **MIT License**. See [LICENSE](LICENSE) for complete details.
