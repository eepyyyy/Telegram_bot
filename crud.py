import aiogram
from database import get_session_maker
import database, sqlmodel, asyncio
import pydantic
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


async def save_track_to_bot_db(track_data: dict):
    async with async_session() as session:

        async with session.begin():
            album_obj = database.Albums(
                album_id=track_data["album_id"],
                album=sample_track_data["album"],
                artist=sample_track_data["artist"]
            )
            await session.merge(album_obj)


asyncio.run(save_track_to_bot_db())