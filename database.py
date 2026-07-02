from typing import Optional
from sqlmodel import SQLModel, Field, select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import sessionmaker
import  asyncio, Schema

# 2. Connection Engine

class Albums(SQLModel, table=True):
    __tablename__ = "albums"
    album_id: str = Field(primary_key=True)
    artist: Optional[str] = None
    album: Optional[str] = None

class Tracks(SQLModel, table=True):
    __tablename__ = "tracks"
    id: str = Field(primary_key=True)
    file_id: Optional[str] = None
    file_unique_id: Optional[str] = None
    song_id: Optional[str] = None
    title: Optional[str] = None
    album: Optional[str] = None
    artist: Optional[str] = None
    url: Optional[str] = None
    album_id:Optional[str] = Field(default=None, foreign_key="albums.album_id")


DATABASE_URL = "postgresql+asyncpg://postgres:user@localhost:5432/test_Tbot"
engine = create_async_engine(DATABASE_URL, echo=True)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

def get_session_maker():
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async_session = get_session_maker()

# Perfect sample data for testing your modern code
sample_track_data = {
    # Album table fields
    "album_id": "alb_4k97x2Lp",
    "album": "Short n' Sweet",
    "artist": "Sabrina Carpenter",

    # Track table fields
    "id": "tr_1v8N0pQz",
    "song_id": "song_espresso_01",
    "title": "Espresso",
    "url": "https://music.apple.com/us/album/espresso/1742230222?i=1742230223",
    "file_id": "CQACAgIAAxkBAAEYv0lm23...H8uAAKyOAACvi7hS6vOa3f7QG80NgQ",
    "file_unique_id": "AgADfQADu7u0Sg"
}

test = Schema.TrackInputSchema(
    album_id="alb_4k97x2Lp",
    album="Short n' Sweet",
    artist="Sabrina Carpenter"
)


async def save_track_to_bot_db(track_data: Schema.TrackInputSchema):
    async with async_session() as session:

        async with session.begin():
            album_obj = Albums(
                album_id=track_data.album_id,
                album=track_data.album,
                artist=track_data.artist
            )
            await session.merge(album_obj)
            track_obj = Tracks(
                album_id=
            )

async def main():
    await init_db()

    print("⏳ Saving test sample data...")
    tests = Schema.TrackInputSchema(**sample_track_data)

    await save_track_to_bot_db(test)


if __name__ == "__main__":
    # This runs your async lifecycle natively in Python
    asyncio.run(main())