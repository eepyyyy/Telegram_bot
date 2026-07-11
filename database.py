import asyncio
import os
from datetime import date
from typing import Optional

from sqlalchemy import BigInteger
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
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


class User(SQLModel, table=True):
    """
    SQLModel for the 'user' table to handle download limits and premium status.
    """
    __tablename__ = "user"
    user_id: Optional[int] = Field(sa_type=BigInteger, primary_key=True)
    is_premium: Optional[bool] = Field(default=False)
    daily_limit: Optional[int] = Field(default=30)
    downloaded_today: Optional[int] = Field(default=0)
    last_download: date = Field(default_factory=date.today)


# Use environment variable for DATABASE_URL with a fallback
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:user@localhost:5432/test_Tbot")

engine = create_async_engine(DATABASE_URL, echo=True)


async def init_db():
    """
    Initializes the database by creating all tables.
    """
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


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