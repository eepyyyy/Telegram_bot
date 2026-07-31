import asyncio
import os
import sys
from typing import List
from database import Albums, Tracks, async_session
from gamdlUrl import get_api, get_artwork_url
from sqlalchemy.future import select

# Semaphore to restrict concurrency to avoid rate limiting
SEMAPHORE = asyncio.Semaphore(15)

# Ensure output streams handle UTF-8 symbols properly on Windows
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

async def update_song_artwork(song_id: str, api):
    async with SEMAPHORE:
        try:
            # 1. Fetch song data from Apple Music API
            song_data = await api.get_song(song_id)
            if not song_data or "data" not in song_data or not song_data["data"]:
                print(f"[{song_id}] No song data found on Apple Music.")
                return

            data = song_data["data"][0]
            attrs = data.get("attributes", {})
            
            # Extract and format artwork URL
            artwork_dict = attrs.get("artwork")
            artwork_url = get_artwork_url(artwork_dict)
            
            if not artwork_url:
                print(f"[{song_id}] No artwork URL found.")
                return
                
            # Extract album_id from relationships
            album_id = None
            try:
                album_id = data["relationships"]["albums"]["data"][0]["id"]
            except (KeyError, IndexError):
                pass

            # 2. Update existing database records
            async with async_session() as session:
                updated = False
                
                # Update Track in database only if artwork doesn't exist
                track = await session.get(Tracks, song_id)
                if track and not track.artwork:
                    track.artwork = artwork_url
                    session.add(track)
                    updated = True
                
                # Update Album in database only if artwork doesn't exist
                if album_id:
                    album = await session.get(Albums, album_id)
                    if album and not album.artwork:
                        album.artwork = artwork_url
                        session.add(album)
                        updated = True
                
                if updated:
                    await session.commit()
                    print(f"[{song_id}] Updated artwork successfully.")
                else:
                    print(f"[{song_id}] Not found in DB (skipped).")
                    
        except Exception as e:
            print(f"[{song_id}] Error occurred: {e}")

async def main():
    print("Fetching tracks from database...")
    
    async with async_session() as session:
        # Fetch up to 10 tracks that have a URL but don't have an artwork URL yet
        stmt = select(Tracks).where(
            Tracks.url.isnot(None),
            (Tracks.artwork.is_(None)) | (Tracks.artwork == "")
        ).limit(1700)
        result = await session.execute(stmt)
        tracks = result.scalars().all()
        
    if not tracks:
        print("No tracks found in the database that are missing artwork.")
        return
        
    print(f"Found {len(tracks)} tracks missing artwork in the database.")
    
    api = await get_api()
    
    # Run the updates concurrently
    tasks = [update_song_artwork(track.song_id, api) for track in tracks]
    await asyncio.gather(*tasks)
    print("All database artwork updates completed!")

if __name__ == "__main__":
    os.environ["PYTHONUTF8"] = "1"
    asyncio.run(main())
