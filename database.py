from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, JSON

# 1. Replace with your actual credentials
DATABASE_URL = "postgresql+asyncpg://postgres:user@localhost:5432/test_Tbot"

# 2. Create the async connection engine
engine = create_async_engine(DATABASE_URL, echo=False)

# 3. Create a session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)


# 4. Base class for our models
class Base(DeclarativeBase):
    pass


# 5. Define the Track Model (Matches your exact pgAdmin columns)
class Track(Base):
    __tablename__ = "tracks"

    track_url: Mapped[str] = mapped_column(String, primary_key=True)
    file_id: Mapped[str] = mapped_column(String, nullable=False)
    file_unique_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String, nullable=True)


# 6. Define the Album Model
class Album(Base):
    __tablename__ = "albums"

    album_url: Mapped[str] = mapped_column(String, primary_key=True)
    track_urls: Mapped[list] = mapped_column(JSON, nullable=False)