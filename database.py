import asyncio
import logging
import os
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import BigInteger, DateTime, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession



class Albums(SQLModel, table=True):
    """
    SQLModel for the 'albums' table.
    """
    __tablename__ = "albums"
    album_id: str = Field(primary_key=True)
    artist: Optional[str] = None
    album: Optional[str] = None
    artwork: Optional[str] = None
    alac_zip_file_id: Optional[str] = None
    aac_zip_file_id: Optional[str] = None
    atmos_zip_file_id: Optional[str] = None
    alac_gofile_url: Optional[str] = None
    aac_gofile_url: Optional[str] = None
    atmos_gofile_url: Optional[str] = None


class Tracks(SQLModel, table=True):
    """
    SQLModel for the 'tracks' table.
    """
    __tablename__ = "tracks"
    file_id: Optional[str] = None
    file_unique_id: Optional[str] = None
    song_id: Optional[str] = Field(primary_key=True)
    title: Optional[str] = None
    album: Optional[str] = None
    artist: Optional[str] = None
    url: Optional[str] = None
    album_id: Optional[str] = Field(default=None, foreign_key="albums.album_id")
    size: Optional[int] = Field(sa_type=BigInteger)
    storefront: Optional[str] = None
    isrc: Optional[str] = None
    artwork: Optional[str] = None
    chat_id: Optional[int] = Field(default=None, sa_type=BigInteger)
    message_id: Optional[int] = Field(default=None)
    updated_at: Optional[datetime] = Field(default=None, sa_type=DateTime(timezone=True))


class AACTracks(SQLModel, table=True):
    """
    SQLModel for the 'aac_tracks' table to store AAC cached audio files.
    """
    __tablename__ = "aac_tracks"
    file_id: Optional[str] = None
    file_unique_id: Optional[str] = None
    song_id: Optional[str] = Field(primary_key=True)
    title: Optional[str] = None
    album: Optional[str] = None
    artist: Optional[str] = None
    url: Optional[str] = None
    album_id: Optional[str] = Field(default=None, foreign_key="albums.album_id")
    size: Optional[int] = Field(sa_type=BigInteger)
    storefront: Optional[str] = None
    isrc: Optional[str] = None
    artwork: Optional[str] = None
    chat_id: Optional[int] = Field(default=None, sa_type=BigInteger)
    message_id: Optional[int] = Field(default=None)
    updated_at: Optional[datetime] = Field(default=None, sa_type=DateTime(timezone=True))


class AtmosTracks(SQLModel, table=True):
    """
    SQLModel for the 'atmos_tracks' table to store Dolby Atmos cached audio files.
    """
    __tablename__ = "atmos_tracks"
    file_id: Optional[str] = None
    file_unique_id: Optional[str] = None
    song_id: Optional[str] = Field(primary_key=True)
    title: Optional[str] = None
    album: Optional[str] = None
    artist: Optional[str] = None
    url: Optional[str] = None
    album_id: Optional[str] = Field(default=None, foreign_key="albums.album_id")
    size: Optional[int] = Field(sa_type=BigInteger)
    storefront: Optional[str] = None
    isrc: Optional[str] = None
    artwork: Optional[str] = None
    chat_id: Optional[int] = Field(default=None, sa_type=BigInteger)
    message_id: Optional[int] = Field(default=None)
    updated_at: Optional[datetime] = Field(default=None, sa_type=DateTime(timezone=True))


class MVTracks(SQLModel, table=True):
    """
    SQLModel for the 'mv_tracks' table to store Music Video cached files.
    """
    __tablename__ = "mv_tracks"
    file_id: Optional[str] = None
    file_unique_id: Optional[str] = None
    song_id: Optional[str] = Field(primary_key=True)
    title: Optional[str] = None
    album: Optional[str] = None
    artist: Optional[str] = None
    url: Optional[str] = None
    album_id: Optional[str] = Field(default=None)
    size: Optional[int] = Field(sa_type=BigInteger)
    storefront: Optional[str] = None
    isrc: Optional[str] = None
    artwork: Optional[str] = None
    chat_id: Optional[int] = Field(default=None, sa_type=BigInteger)
    message_id: Optional[int] = Field(default=None)
    resolution: Optional[str] = Field(default=None)
    codec: Optional[str] = Field(default=None)
    updated_at: Optional[datetime] = Field(default=None, sa_type=DateTime(timezone=True))



class User(SQLModel, table=True):
    """
    SQLModel for the 'user' table to handle download limits and premium status.
    """
    __tablename__ = "user"
    user_id: Optional[int] = Field(sa_type=BigInteger, primary_key=True)
    is_premium: Optional[bool] = Field(default=False)
    daily_limit: Optional[int] = Field(default=50)
    downloaded_today: Optional[int] = Field(default=0)
    last_download: date = Field(default_factory=date.today)
    download_count: Optional[int] = Field(default=0)


class DownloadHistory(SQLModel, table=True):
    """
    SQLModel for the 'download_history' table to track user downloads.
    """
    __tablename__ = "download_history"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(sa_type=BigInteger, index=True)
    song_id: Optional[str] = None
    format_type: str = Field(index=True)  # alac, aac, atmos, mv
    is_cached: bool = Field(default=False)
    size: Optional[int] = Field(default=0, sa_type=BigInteger)
    downloaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_type=DateTime(timezone=True))


load_dotenv()

# Require the database URL to be configured outside source control.
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing. Add it to your .env file.")

echo_sql = os.getenv("SQL_ECHO", "false").lower() in ("true", "1")
engine = create_async_engine(
    DATABASE_URL,
    echo=echo_sql,
    pool_pre_ping=True,
    pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
    pool_recycle=1800,
)


async def init_db():
    """
    Initializes the database by creating all tables and adding missing columns safely.
    """
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    migration_stmts = [
        "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS chat_id BIGINT;",
        "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS message_id INT;",
        "ALTER TABLE tracks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();",
        "ALTER TABLE aac_tracks ADD COLUMN IF NOT EXISTS chat_id BIGINT;",
        "ALTER TABLE aac_tracks ADD COLUMN IF NOT EXISTS message_id INT;",
        "ALTER TABLE aac_tracks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();",
        "ALTER TABLE atmos_tracks ADD COLUMN IF NOT EXISTS chat_id BIGINT;",
        "ALTER TABLE atmos_tracks ADD COLUMN IF NOT EXISTS message_id INT;",
        "ALTER TABLE atmos_tracks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();",
        "ALTER TABLE mv_tracks ADD COLUMN IF NOT EXISTS chat_id BIGINT;",
        "ALTER TABLE mv_tracks ADD COLUMN IF NOT EXISTS message_id INT;",
        "ALTER TABLE mv_tracks ADD COLUMN IF NOT EXISTS resolution VARCHAR;",
        "ALTER TABLE mv_tracks ADD COLUMN IF NOT EXISTS codec VARCHAR;",
        "ALTER TABLE mv_tracks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();",
        "ALTER TABLE albums ADD COLUMN IF NOT EXISTS alac_zip_file_id VARCHAR;",
        "ALTER TABLE albums ADD COLUMN IF NOT EXISTS aac_zip_file_id VARCHAR;",
        "ALTER TABLE albums ADD COLUMN IF NOT EXISTS atmos_zip_file_id VARCHAR;",
        "ALTER TABLE albums ADD COLUMN IF NOT EXISTS alac_gofile_url VARCHAR;",
        "ALTER TABLE albums ADD COLUMN IF NOT EXISTS aac_gofile_url VARCHAR;",
        "ALTER TABLE albums ADD COLUMN IF NOT EXISTS atmos_gofile_url VARCHAR;",
        "CREATE EXTENSION IF NOT EXISTS pg_trgm;",
        "CREATE INDEX IF NOT EXISTS idx_tracks_combined_search ON tracks USING gin ((LOWER(title || ' ' || artist || ' ' || COALESCE(album, '') || ' ' || COALESCE(isrc, ''))) gin_trgm_ops);",
        "CREATE INDEX IF NOT EXISTS idx_aac_combined_search ON aac_tracks USING gin ((LOWER(title || ' ' || artist || ' ' || COALESCE(album, '') || ' ' || COALESCE(isrc, ''))) gin_trgm_ops);",
        "CREATE INDEX IF NOT EXISTS idx_atmos_combined_search ON atmos_tracks USING gin ((LOWER(title || ' ' || artist || ' ' || COALESCE(album, '') || ' ' || COALESCE(isrc, ''))) gin_trgm_ops);",
        "CREATE INDEX IF NOT EXISTS idx_mv_combined_search ON mv_tracks USING gin ((LOWER(title || ' ' || artist || ' ' || COALESCE(album, '') || ' ' || COALESCE(isrc, ''))) gin_trgm_ops);",
    ]

    for stmt in migration_stmts:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(stmt))
            logging.info(f"✅ Migration applied: {stmt}")
        except Exception as e:
            logging.warning(f"⚠️ Migration notice for [{stmt}]: {e}")

    logging.info("🎉 Database schema initialized and all migrations verified.")




def get_session_maker():
    """
    Returns a sessionmaker for AsyncSession.
    """
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async_session = get_session_maker()


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
    print("🚀 Starting database migrations...")
    await init_db()
    print("✅ All database migrations finished successfully!")


if __name__ == "__main__":
    asyncio.run(main())
