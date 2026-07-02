from typing import Optional
from pydantic import BaseModel

class TrackSchema(BaseModel):
    song_id: str
    album_id:str
    title: str
    artist: str | None = None
    album: str | None = None
    url: str

class TrackInputSchema(BaseModel):
    album_id: str | None = None
    album: str | None = None
    artist: str | None = None
    id: str | None = None
    song_id: str | None = None
    title: str | None = None
    url: str | None = None
    file_id: str | None = None
    file_unique_id: str | None = None