I see exactly what happened—the previous attempt flattened the whole tree structure into a broken inline mess like in your screenshot. Let's fix that formatting so it renders as a clean, properly aligned project tree alongside the rest of the text.

Here is the entire, raw `README.md` file in one single, complete code block:

```markdown
# 🎵 Apple Music High-Fidelity Downloader Telegram Bot

An elegant, highly concurrent, and asynchronous Telegram bot built with **Aiogram 3** and **SQLModel** (SQLAlchemy). It facilitates pulling studio-grade audio profiles (AAC, Lossless ALAC, Dolby Atmos) using a background worker cluster powered by `gamdl` while leveraging a strict per-user request queuing system to avoid race conditions.

---

## ✨ Features

- **Concurrent Processing Engine:** Implements a global worker pool (3 concurrent workers) paired with a strict **Per-User Async Lock (`asyncio.Lock`)**[cite: 3, 4]. Multiple users download at the same time, but a single user's requests queue sequentially to maximize runtime stability.
- **Intelligent Database Caching:** Checks incoming ISRCs against local PostgreSQL tracking tables before downloading[cite: 8]. Matches are instantly delivered via Telegram cached `file_id` parameters, conserving network bandwidth and API tokens[cite: 4].
- **FSM Dynamic Navigation:** Integrates a robust Finite State Machine (FSM) via Aiogram Routers, enabling user interactive sorting across Full Albums, Singles, Live Concerts, and Compilations[cite: 9].
- **Native Metadata Extraction:** Reads `.m4a` file headers using standard atoms mapping (`©nam`, `©ART`, `covr`) to automatically append high-quality dynamic album thumbnails and correct tags during execution[cite: 1].
- **Anti-Spam Quota Limiting:** Tracks rolling quotas locally via database validation matrices, halting standard user backlogs gracefully when daily boundaries are hit[cite: 4, 7].

```

## 🏗️ Project Architecture Overview

```text
.
├── index.py          # Main entrypoint, lifecycle init, and queue worker pool[cite: 4]
├── artist.py         # Advanced FSM multi-select callback routers[cite: 9]
├── gamdlUrl.py       # Apple Music netscape cookie interface configuration[cite: 5]
├── database.py       # SQLModel AsyncEngine declarations & target schemas[cite: 7]
├── Schema.py         # Core Pydantic validation boundaries[cite: 2]
├── utils.py          # Mutagen metadata parsing and ASCII normalization text utility[cite: 1]
└── queues.py         # Thread-safe global structural locks and storage fields[cite: 3]

```

## 🚀 Infrastructure & Remote Networking (Cloudflare Tunnel)

When connecting your local deployment back to a secure cloud database service instance routed over Cloudflare network infrastructure without exposing local machines to the open internet, run the following inbound terminal bridge command:

```bash
cloudflared access tcp --hostname sqldb.eepy.in --url localhost:5432

```
This handles secure tunneling of the TCP stream directly between your local PostgreSQL database (`localhost:5432`) and the remote infrastructure zone.
---

## 🛠️ Step-by-Step Local Deployment

### 1. Prerequisites

Ensure you have system-level access to the following dependencies:

* **Python 3.10+**
* **FFmpeg & Bento4** (Required by `gamdl` for file assembly/muxing)
* **PostgreSQL Database**

### 2. Environment Configuration

Create a `.env` file within your project root folder and specify your bot credentials and database engine target URI strings:

```env
TOKEN_API="YOUR_TELEGRAM_BOT_TOKEN"
DATABASE_URL="postgresql+asyncpg://postgres:user@localhost:5432/test_Tbot"
```

### 3. Apple Music Authorization

Export a Netscape-format cookie file containing an authorized active subscription token session from your browser, name it **`cookies.txt`**, and place it directly into the application's root folder directory.

### 4. Installation & Start Execution

Install all mandatory structural modules via your terminal and kick off the daemon execution:

```bash
# Install core runtime packages
pip install aiogram sqlmodel asyncpg mutagen pydantic python-dotenv gamdl

# Launch the engine process
python index.py
```

---

## 🔧 Core Mechanics Explained

### The Microsecond Sandbox Fix

To prevent cross-worker interference where overlapping tasks for the same user accidentally deleted concurrent assets, directories are isolated via an event-loop clock mapping signature:

```python
unique_task_id = f"{msg.message_id}_{int(asyncio.get_event_loop().time() * 1000)}"
task_output_dir = os.path.join("./downloads", unique_task_id)
```

### Clean Asynchronous Lock Releases

Users are cleanly removed from runtime anti-spam state dictionaries strictly when their total queue tracking length reads zero and their explicit worker process lock state toggles to unrestricted:

```python
if download_queue.empty() and not user_lock.locked():
    user_in_queue.discard(user_id)
```
