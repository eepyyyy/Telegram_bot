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
    subgraph Telegram_Network [Telegram Ecosystem]
        User([👤 User / Client])
        StorageChannel[📦 Private Storage Channel]
    end

    subgraph Bot_Core [Telegram Bot Service (index.py)]
        WebhookReceiver[🌐 Webhook Receiver / FastHTTP]
        Dispatcher[⚡ Aiogram 3 Dispatcher]
        CrossResolver[🔀 Cross-Platform Matcher<br/>(Spotify / YouTube / Tidal)]
        
        subgraph Queue_Engine [In-Memory Queues & Worker Pools]
            Q_ALAC[Queue: ALAC Lossless]
            Q_Atmos[Queue: Dolby Atmos]
            Q_AAC[Queue: AAC 256k]
            Q_MV[Queue: Music Videos]
        end
    end

    subgraph Processing_Layer [Downloader & Remuxer Engine]
        GamdlEngine[📥 gamdl / yt-dlp Core]
        Remuxer[🎬 Bento4 & FFmpeg Pipeline]
    end

    subgraph Data_Storage [Data & Storage Tier]
        Postgres[(🐘 PostgreSQL Database<br/>SQLModel / AsyncPG)]
        GoFile[☁️ GoFile High-Speed Fallback]
    end

    subgraph Companion_Services [Companion Services]
        AdminUI[🖥️ Admin Dashboard (React / Vite)]
        StreamServer[📻 HTTP Stream Server<br/>(Pyrogram MTProto Range Requests)]
    end

    User <-->|Bot Commands & Links| WebhookReceiver
    WebhookReceiver --> Dispatcher
    Dispatcher --> CrossResolver
    CrossResolver --> Queue_Engine
    
    Q_ALAC --> GamdlEngine
    Q_Atmos --> GamdlEngine
    Q_AAC --> GamdlEngine
    Q_MV --> GamdlEngine
    
    GamdlEngine --> Remuxer
    Remuxer -->|Upload Media| StorageChannel
    Remuxer -->|Large Files >2GB| GoFile
    StorageChannel -->|Cache File ID & Message ID| Postgres
    StorageChannel -->|Forward / Copy Cached Media| User

    AdminUI <-->|REST API + Telemetry| Bot_Core
    StreamServer <-->|Query Cached IDs| Postgres
    StreamServer <-->|Stream Audio Chunks| StorageChannel
```

---

### 2. End-to-End Media Ingestion & Delivery Flow

```mermaid
sequenceDiagram
    autonumber
    actor User as 👤 User
    participant Bot as 🤖 Bot Handler (index.py)
    participant DB as 🐘 PostgreSQL
    participant Queue as 📋 Format Queue
    participant Worker as ⚙️ Worker Pool
    participant Apple as 🍏 Apple Music API
    participant Telegram as 📦 Telegram Storage Channel

    User->>Bot: Send Apple Music URL (or Spotify/YouTube link)
    Bot->>Bot: Normalize URL & Parse Options (-n / --no-cache)
    
    alt Cache Lookup (Unless -n specified)
        Bot->>DB: Query track by song_id / format
        DB-->>Bot: Return cached chat_id & message_id
        alt Already in Database
            Bot->>Telegram: copy_message() to User
            Telegram-->>User: ⚡ Instant Media Delivery (0s delay)
        end
    end

    opt Not in Cache or No-Cache Flag
        Bot->>Queue: Enqueue Task (Per-User Serialized Lock)
        Queue->>Worker: Dispatch Job to Free Worker
        Worker->>Apple: Fetch Track / Album Metadata & Decryption Keys
        Worker->>Worker: Download Audio Streams (gamdl / yt-dlp)
        Worker->>Worker: Remux, Embed Cover Artwork & Tags (FFmpeg)
        Worker->>Telegram: send_audio() / send_document() to Storage Channel
        Telegram-->>Worker: Return message_id & file_id
        Worker->>DB: Save Track, File ID, Format & Media Size
        Worker->>Telegram: Forward or Copy to User Chat
        Telegram-->>User: 🎧 Completed Audio / Video Delivered
    end
```

---

### 3. Task Queue State Machine & Self-Healing Lifecycle

```mermaid
stateDiagram-v2
    [*] --> Idle

    Idle --> Queued: User Submits URL
    Queued --> Active: Worker Slot Available & User Lock Acquired
    
    state Active {
        [*] --> FetchingMetadata
        FetchingMetadata --> Downloading: Keys & Stream Acquired
        Downloading --> Remuxing: Streams Complete
        Remuxing --> Uploading: Tags & Artwork Applied
        Uploading --> [*]: Sent to Telegram / GoFile
    }

    Active --> Completed: Success & Cached
    Active --> Failed: Exception / DRM Timeout
    Active --> Cancelled: User / Admin Cancelled
    Active --> SelfHealed: Inactivity Timeout (>15m)

    Completed --> Idle: Release User Lock
    Failed --> Idle: Notify User & Release Lock
    Cancelled --> Idle: Clean Temp Files & Release Lock
    SelfHealed --> Idle: Reset Flags & Evict Stale Task
```

---

### 4. Cross-Platform Matcher Flow

```mermaid
flowchart LR
    A[External Link<br/>Spotify / YouTube / Tidal] --> B{URL Parser}
    B -->|Spotify| C[Extract Track/Artist/ISRC]
    B -->|YouTube| D[Extract Video Title & Channel]
    B -->|Tidal| E[Extract Title & Artist]
    
    C --> F[Apple Music Storefront Search API]
    D --> F
    E --> F
    
    F --> G{Match Found?}
    G -->|Yes| H[Resolve Canonical Apple Music ID]
    G -->|No| I[Report Not Found to User]
    H --> J[Trigger Lossless Download Pipeline]
```

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
├── dashboard/                 # React 18 + Vite + Tailwind/Lucide administrator dashboard
├── server/                    # Standalone Pyrogram MTProto HTTP range streaming microservice
├── web/                       # Alternative local web downloader service
├── scripts/                   # Database backup, restore, and maintenance utilities
├── docker-compose.yml         # Containerized production multi-service deployment
├── Dockerfile                 # Multi-stage production container image
├── pyproject.toml             # Python 3.14 dependencies and project manifest
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
