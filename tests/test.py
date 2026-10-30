from typing import List

from gamdlUrl import get_any_url
from database import async_session, Albums, Tracks
import asyncio

async def update_db(lists: List[str]):
    async with async_session() as session:
        for song in lists:
            try:
                track_metadat = await get_any_url(song)
                for track_data in track_metadat:
                    if track_data.album_id:
                        album = await session.get(Albums, track_data.album_id)
                        if album:
                            album.artwork = track_data.artwork
                            session.add(album)
                await session.commit()
                print(f"Successfully updated artwork for: {song}")

            except Exception as e:
                await session.rollback()
                print(f"Error updating {song}: {e}")