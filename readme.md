# Apple Music Telegram Bot

An asynchronous Telegram bot and companion web stack for cataloguing, downloading, caching, and streaming Apple Music media. The project supports ALAC/lossless audio, AAC, Dolby Atmos, and music videos, with PostgreSQL metadata storage and Telegram-backed media delivery.

> This project relies on third-party services and tools such as Telegram and `gamdl`. Configure and use it only in accordance with their terms and applicable law.

## What it does

- Accepts Apple Music links through the Telegram bot.
- Fetches metadata for songs, albums, playlists, and artists.
- Queues downloads by media format and serializes each user's work within a queue.
- Uses PostgreSQL to cache metadata and Telegram file/message IDs.
- Delivers cached media through Telegram and exposes a streaming/download API.
- Provides an administrator dashboard for queue controls, telemetry, logs, users, and artist caching.
- Creates database backups locally, through the bot, and optionally through GitHub Actions/Releases.

## Architecture

```text
                         Telegram updates (webhook)
                                     |
                                     v
                         +-----------------------+
                         |  Bot service           |
                         |  index.py              |
                         +-----------------------+
                           |     |          |
                           |     |          +--> Admin REST API + dashboard assets
                           |     |
                           |     +--> Format queues and workers
                           |          ALAC | lossless | AAC | Atmos | music video
                           v
                 Apple Music metadata + gamdl / yt-dlp
                           |
                           v
                  Telegram media upload and delivery
                           |
                           v
              +------------------------+     +----------------------+
              | PostgreSQL             |<--->| Stream service       |
              | tracks, albums, users, |     | server/main.py       |
              | download history       |     | Telegram MTProto     |
              +------------------------+     +----------------------+
                           ^
                           |
              +------------------------+
              | Optional web service   |
              | web/main.py            |
              | local file downloads   |
              +------------------------+
```

### Main components

| Component | Entry point | Responsibility |
| --- | --- | --- |
| Telegram bot | `index.py` | Receives webhook updates, registers handlers, starts workers, and serves the admin API/dashboard. |
| Format handlers | `lossless.py`, `aac.py`, `atmos.py`, `mv.py` | Parse commands, enqueue work, run format-specific workers, and deliver media. |
| Metadata layer | `gamdlUrl.py`, `gamdlHelpUrl.py`, `app/gamdlapi.py` | Normalizes Apple Music URLs and retrieves metadata. |
| Queue state | `queues.py`, `bot_control.py` | Holds in-memory queues, per-user locks, active tasks, pause state, and telemetry logs. |
| Data layer | `database.py`, `crud.py`, `schema.py` | Defines SQLModel tables and data access for media, albums, users, and download history. |
| Admin dashboard | `dashboard/`, `admin_routes.py` | React/Vite UI and the authenticated operational API it calls. |
| Stream API | `server/main.py` | Streams cached Telegram files over HTTP using Pyrogram and supports range requests. |
| Web downloader | `web/main.py` | Hosts a standalone web UI/API and downloads media to local storage. |
| Operations | `scripts/`, `.github/workflows/db_backup.yml` | Provides backups, migration helpers, and scheduled database backup automation. |

### Data flow

1. A user sends an Apple Music URL to the bot.
2. A handler normalizes the URL and queries metadata.
3. The bot checks PostgreSQL for a suitable cached copy.
4. If absent, the handler adds a job to its format-specific queue.
5. A worker downloads and processes the media, then uploads it to the configured Telegram storage channel.
6. The worker stores metadata and Telegram `chat_id`/`message_id` values in PostgreSQL.
7. Future requests can use the cached Telegram media. The stream service reads those identifiers and serves the file over HTTP.

## Repository layout

```text
.
├── index.py                   # Bot, webhook server, workers, admin dashboard serving
├── aac.py / atmos.py          # Format-specific audio handlers and workers
├── lossless.py / mv.py        # Lossless and music-video handlers and workers
├── artist.py / help.py        # Bot interaction flows
├── database.py / crud.py      # PostgreSQL models and data access
├── queues.py / bot_control.py # In-memory jobs, locks, active-task and admin state
├── admin_routes.py            # Dashboard authentication and operational endpoints
├── server/                    # Telegram-backed HTTP streaming service
├── web/                       # Optional local-file web downloader service
├── dashboard/                 # React/Vite administrator dashboard
├── app/                       # Static web application and metadata API
├── scripts/                   # Backup and migration utilities
└── .github/workflows/         # Scheduled PostgreSQL backup workflow
```

## Prerequisites

- Python 3.14 or later (the version declared in `pyproject.toml`)
- PostgreSQL
- Node.js and npm (only for dashboard development/builds)
- `gamdl` and its system dependencies, including FFmpeg and Bento4 where required
- A Telegram bot token and a Telegram API ID/hash for the streaming client
- A reachable webhook URL when running the bot in webhook mode

## Configuration

1. Copy `.env.example` to `.env`.
2. Replace every placeholder with environment-specific values.
3. Keep `.env`, cookies, sessions, downloads, and backups outside source control.

| Variable | Used by | Purpose |
| --- | --- | --- |
| `TOKEN_API` | Bot and stream client | Telegram bot token. |
| `API_ID`, `API_HASH` | Stream service | Telegram MTProto application credentials. |
| `DATABASE_URL` | All services | PostgreSQL async SQLAlchemy URL. |
| `WEBHOOK_HOST`, `WEBHOOK_PATH`, `WEBHOOK_SECRET` | Bot | Public webhook configuration. |
| `WEBHOOK_LISTEN_HOST`, `WEBHOOK_LISTEN_PORT` | Bot | Local listener address and port. |
| `STORAGE_CHANNEL_ID` | Bot and stream service | Telegram channel where media is cached. |
| `STREAM_SERVER_URL` | Bot and web services | Public stream-server base URL. |
| `ADMIN_PASSWORD`, `JWT_SECRET` | Dashboard API | Administrator authentication credentials. Use strong unique values. |
| `WORKER_CONCURRENCY` and format-specific worker variables | Bot | Number of background workers per format. |

For Apple Music access, place an authorized Netscape-format cookie file at `cookies.txt` in the project root. It is intentionally ignored by Git.

## Installation

This repository includes a `uv.lock`, so `uv` is the preferred installer:

```powershell
uv sync
```

Alternatively, install the package dependencies into a virtual environment using your preferred Python package manager.

Build the dashboard when serving it from the bot service:

```powershell
Set-Location dashboard
npm ci
npm run build
Set-Location ..
```

## Running services

Run only the services needed for your deployment. All services read the root `.env` file.

### Telegram bot and dashboard

```powershell
uv run python index.py
```

The bot waits for the local Telegram Bot API server configured by `LOCAL_SERVER_URL`, initializes the database, starts workers, sets its webhook, and serves the dashboard at `/dashboard/` when `dashboard/dist` exists.

### Streaming service

```powershell
uv run python -m server.main
```

This service uses Pyrogram to retrieve cached media from Telegram. It exposes a health endpoint at `/health` and serves streaming/download routes backed by database records.

### Optional web downloader

```powershell
uv run python -m web.main
```

This standalone service hosts a browser UI plus an API for local media downloads. It is separate from the Telegram-backed streaming service.

### Dashboard development server

```powershell
Set-Location dashboard
npm run dev
```

The Vite development server proxies `/api` calls to `http://localhost:8080` by default.

## Operations

### Database backup

Run a local backup manually:

```powershell
uv run python scripts/backup_db.py --help
```

The bot also starts a periodic backup worker. The GitHub Actions workflow in `.github/workflows/db_backup.yml` can create scheduled backups when its `DATABASE_URL` repository secret is configured and reachable from GitHub Actions.

### Useful endpoints

| Service | Endpoint | Purpose |
| --- | --- | --- |
| Bot | `POST {WEBHOOK_PATH}` | Telegram webhook receiver. |
| Bot | `/dashboard/` | Administrator dashboard after building the frontend. |
| Bot | `/api/admin/*` | Dashboard control and telemetry API. |
| Stream | `/health` | Stream service health check. |
| Stream | `/stream/{format}/{song_id}` | Stream a Telegram-cached media record. |
| Stream | `/download/{format}/{song_id}` | Download a Telegram-cached media record. |
| Web | `/health` | Web downloader health check. |

## Development notes

- `queues.py` and `bot_control.py` are in-memory state. A restart clears queued jobs, active task information, dashboard sessions, and pause/maintenance state.
- Database schema initialization and compatibility changes currently run during service startup through `database.init_db()`.
- The dashboard source lives in `dashboard/src`; `dashboard/dist` is the built output served by the bot/web application.
- Before deploying changes, compile Python modules and build the dashboard:

```powershell
.\.venv\Scripts\python.exe -m compileall -q .
Set-Location dashboard; npm run build
```

## Security checklist

- Use long, unique values for all secrets—especially `WEBHOOK_SECRET`, `ADMIN_PASSWORD`, and `JWT_SECRET`.
- Never commit `.env`, `cookies.txt`, Telegram `.session` files, media, or database backups.
- Put the dashboard and admin API behind HTTPS and restrict access at the reverse proxy/firewall.
- Configure PostgreSQL with a dedicated least-privilege application user and regular, verified backups.

## License

No license is currently declared. Add one before distributing or accepting external contributions.
