import asyncio
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


load_dotenv()

# Require the database URL to be configured outside source control.
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing. Add it to your .env file.")

engine = create_async_engine(DATABASE_URL, echo=True)


async def init_db():
    """
    Initializes the database by creating all tables and adding missing columns safely.
    """
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        await conn.execute(text("ALTER TABLE tracks ADD COLUMN IF NOT EXISTS chat_id BIGINT;"))
        await conn.execute(text("ALTER TABLE tracks ADD COLUMN IF NOT EXISTS message_id INT;"))
        await conn.execute(text("ALTER TABLE tracks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();"))
        await conn.execute(text("ALTER TABLE aac_tracks ADD COLUMN IF NOT EXISTS chat_id BIGINT;"))
        await conn.execute(text("ALTER TABLE aac_tracks ADD COLUMN IF NOT EXISTS message_id INT;"))
        await conn.execute(text("ALTER TABLE aac_tracks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();"))
        await conn.execute(text("ALTER TABLE atmos_tracks ADD COLUMN IF NOT EXISTS chat_id BIGINT;"))
        await conn.execute(text("ALTER TABLE atmos_tracks ADD COLUMN IF NOT EXISTS message_id INT;"))
        await conn.execute(text("ALTER TABLE atmos_tracks ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_tracks_combined_search ON tracks USING gin ((LOWER(title || ' ' || artist || ' ' || COALESCE(album, '') || ' ' || COALESCE(isrc, ''))) gin_trgm_ops);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_aac_combined_search ON aac_tracks USING gin ((LOWER(title || ' ' || artist || ' ' || COALESCE(album, '') || ' ' || COALESCE(isrc, ''))) gin_trgm_ops);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_atmos_combined_search ON atmos_tracks USING gin ((LOWER(title || ' ' || artist || ' ' || COALESCE(album, '') || ' ' || COALESCE(isrc, ''))) gin_trgm_ops);"))



def get_session_maker():
    """
    Returns a sessionmaker for AsyncSession.
    """
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async_session = get_session_maker()


async def main():
    await init_db()


if __name__ == "__main__":
    asyncio.run(main())
