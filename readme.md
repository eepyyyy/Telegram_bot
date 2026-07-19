# Apple Music Downloader Telegram Bot

A high-fidelity Telegram bot for downloading audio tracks, albums, and playlists directly from Apple Music.

## Features

- **High Quality Audio:** Supports AAC (256kbps) and Lossless ALAC up to 24-bit/192kHz.
- **Caching System:** Uses a PostgreSQL database to cache Telegram file IDs, ensuring instant delivery for previously downloaded tracks.
- **User Management:** Implements daily download limits for standard users and unlimited access for premium users.
- **Concurrent Processing:** Utilizes a worker-based queue system to handle multiple download requests simultaneously.
- **Metadata Extraction:** Automatically extracts artist, title, duration, and cover art from downloaded files for a rich Telegram audio experience.

## Architecture

The bot is built using the following components:

- **aiogram:** A modern and fully asynchronous framework for Telegram Bot API.
- **gamdl:** A powerful tool for downloading Apple Music tracks.
- **SQLModel / SQLAlchemy:** For asynchronous database interactions with PostgreSQL.
- **mutagen:** For extracting metadata from M4A files.

## Project Structure

- `index.py`: The main entry point and bot logic.
- `database.py`: Database models and connection setup.
- `crud.py`: Create, Read, Update, and Delete operations for the database.
- `gamdlUrl.py`: Logic for fetching metadata from Apple Music URLs.
- `utils.py`: Utility functions for text normalization and metadata extraction.
- `Schema.py`: Pydantic models for data validation and transfer.
- `token_tl.py`: Telegram bot token storage.

## Setup

1.  **Clone the repository.**
2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
3.  **Configure Environment Variables:**
    - `DATABASE_URL`: Your PostgreSQL connection string (e.g., `postgresql+asyncpg://user:pass@localhost:5432/dbname`).
    - Update `token_tl.py` with your `TOKEN_API`.
4.  **Apple Music Cookies:**
    - Place a `cookies.txt` file (Netscape format) in the root directory to authenticate with Apple Music.
5.  **Run the bot:**
    ```bash
    python index.py
    ```

## Database Schema

- `User`: Tracks user status, daily limits, and download count.
- `Albums`: Stores album information.
- `Tracks`: Stores track information including Telegram `file_id` for caching.

## Contributing

Suggestions and improvements are welcome! Please feel free to open an issue or submit a pull request.

- cloudflared access tcp --hostname sqldb.eepy.in --url localhost:5432