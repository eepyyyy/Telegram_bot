from pydantic import BaseModel

class TrackSchema(BaseModel):
    song_id: str
    title: str
    artist: str | None = None
    album: str | None = None
    url: str