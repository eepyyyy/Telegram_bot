from typing import Optional
from pydantic import BaseModel, Field



class TrackSchema(BaseModel):
    """
    Schema representing a track's basic information.
    """
    song_id: str
    album_id: str
    title: str
    artist: Optional[str] = None
    album: Optional[str] = None
    url: str


class TrackInputSchema(BaseModel):
    """
    Schema for track input data, including optional fields for database caching and metadata.
    """
    album_id: Optional[str] = None
    album: Optional[str] = None
    artist: Optional[str] = None
    song_id: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    file_id: Optional[str] = None
    file_unique_id: Optional[str] = None
    size: Optional[int] = None
    storefront: Optional[str] = None
    isrc: Optional[str] = None
    artwork: Optional[str] = None
    chat_id: Optional[int] = None
    message_id: Optional[int] = None
    audio_traits: Optional[list[str]] = Field(default_factory=list)
    video_traits: Optional[list[str]] = Field(default_factory=list)
