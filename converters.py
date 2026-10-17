import re
import html
import asyncio
import logging
from typing import Optional, Tuple, Dict, Any
from urllib.parse import quote, urlparse

import aiohttp
import gamdlHelpUrl

logger = logging.getLogger("converters")

SPOTIFY_TRACK_RE = re.compile(r"https?://open\.spotify\.com/track/([a-zA-Z0-9]+)")
SPOTIFY_ALBUM_RE = re.compile(r"https?://open\.spotify\.com/album/([a-zA-Z0-9]+)")
SPOTIFY_LINK_RE = re.compile(r"https?://spotify\.link/([a-zA-Z0-9]+)")

YOUTUBE_RE = re.compile(r"https?://(?:www\.|m\.)?(?:music\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]+)")
YOUTU_BE_RE = re.compile(r"https?://youtu\.be/([a-zA-Z0-9_-]+)")

TIDAL_TRACK_RE = re.compile(r"https?://(?:listen\.|www\.)?tidal\.com/(?:browse/)?track/([0-9]+)")
TIDAL_ALBUM_RE = re.compile(r"https?://(?:listen\.|www\.)?tidal\.com/(?:browse/)?album/([0-9]+)")


def is_cross_platform_url(url: str) -> Optional[Tuple[str, str]]:
    """
    Checks if a URL belongs to Spotify, YouTube, or Tidal.
    Returns (platform, media_type) if recognized, or None.
    media_type can be 'track' or 'album'.
    """
    if not url:
        return None
    url_clean = url.strip()

    if SPOTIFY_TRACK_RE.search(url_clean) or SPOTIFY_LINK_RE.search(url_clean):
        return ("spotify", "track")
    if SPOTIFY_ALBUM_RE.search(url_clean):
        return ("spotify", "album")

    if YOUTUBE_RE.search(url_clean) or YOUTU_BE_RE.search(url_clean):
        return ("youtube", "track")

    if TIDAL_TRACK_RE.search(url_clean):
        return ("tidal", "track")
    if TIDAL_ALBUM_RE.search(url_clean):
        return ("tidal", "album")

    return None


def clean_music_title(title: str) -> str:
    """
    Cleans noisy video and track titles (e.g. from YouTube) for accurate Apple Music matching.
    """
    if not title:
        return ""
    # Unescape HTML entities
    cleaned = html.unescape(title)

    # Remove brackets containing video tags, quality, etc.
    bracket_patterns = [
        r"\s*[\(\[](?:Official\s*(?:Music\s*)?Video|Official\s*Audio|Lyric\s*Video|Lyrics|Visualizer|Audio|HD|4K|HQ|Explicit|Video|Remastered|Live)[\)\]]",
        r"\s*[\(\[](?:Video\s*Clip|Music\s*Video|Clip\s*Officiel)[\)\]]",
        r"\s*[\(\[]HD\s*Audio[\)\]]",
        r"\s*[\(\[]Official[\)\]]",
    ]
    for pat in bracket_patterns:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)

    # Strip trailing quotes or dashes
    cleaned = cleaned.strip(" -\"'")
    return cleaned.strip()


async def extract_spotify_metadata(url: str) -> Optional[Dict[str, Any]]:
    """
    Extracts title and artist from Spotify URL using Spotify oEmbed and page metadata.
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    async with aiohttp.ClientSession(headers=headers) as session:
        # 1. Resolve spotify.link redirects if applicable
        target_url = url
        if "spotify.link" in url:
            try:
                async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    target_url = str(resp.url)
            except Exception:
                pass

        # 2. Query Spotify oEmbed
        title = None
        oembed_url = f"https://open.spotify.com/oembed?url={quote(target_url)}"
        try:
            async with session.get(oembed_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    title = data.get("title")
        except Exception as e:
            logger.warning(f"Spotify oEmbed fetch error: {e}")

        # 3. Query page HTML for artist name and full title
        artist = None
        media_type = "album" if "/album/" in target_url else "track"
        try:
            async with session.get(target_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    html_text = await resp.text()
                    # meta <title>: "Title - song and lyrics by Artist | Spotify"
                    title_match = re.search(r"<title>([^<]+)</title>", html_text)
                    if title_match:
                        raw_t = html.unescape(title_match.group(1))
                        # format: "<Track> - song and lyrics by <Artist> | Spotify"
                        m = re.match(r"^(.*?)\s*-\s*(?:song and lyrics|song|album)\s+by\s+(.*?)\s*\|\s*Spotify", raw_t, re.IGNORECASE)
                        if m:
                            title = m.group(1).strip()
                            artist = m.group(2).strip()

                    # og:description fallback: "Artist · Album · Song · 2020"
                    if not artist:
                        desc_match = re.search(r'<meta property="og:description" content="([^"]+)"', html_text)
                        if desc_match:
                            desc_parts = [p.strip() for p in desc_match.group(1).split("·")]
                            if desc_parts:
                                artist = desc_parts[0]
        except Exception as e:
            logger.warning(f"Spotify HTML metadata fetch error: {e}")

        if title:
            return {
                "title": title,
                "artist": artist or "",
                "type": media_type,
                "source_url": target_url,
            }
        return None


async def extract_youtube_metadata(url: str) -> Optional[Dict[str, Any]]:
    """
    Extracts title and channel from YouTube URL using YouTube oEmbed.
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    async with aiohttp.ClientSession(headers=headers) as session:
        oembed_url = f"https://www.youtube.com/oembed?url={quote(url)}&format=json"
        try:
            async with session.get(oembed_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    raw_title = data.get("title", "")
                    author = data.get("author_name", "")
                    cleaned_title = clean_music_title(raw_title)

                    # Often YouTube music titles are: "Artist - Title"
                    artist = author
                    song_title = cleaned_title
                    if " - " in cleaned_title:
                        parts = cleaned_title.split(" - ", 1)
                        artist = parts[0].strip()
                        song_title = parts[1].strip()

                    # Remove 'VEVO' or 'Official' from artist name if present
                    artist = re.sub(r"(?:VEVO|Official|Topic)$", "", artist, flags=re.IGNORECASE).strip()

                    return {
                        "title": song_title,
                        "artist": artist,
                        "type": "track",
                        "source_url": url,
                    }
        except Exception as e:
            logger.warning(f"YouTube oEmbed error: {e}")
        return None


async def extract_tidal_metadata(url: str) -> Optional[Dict[str, Any]]:
    """
    Extracts title and artist from Tidal URL using Tidal oEmbed.
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    async with aiohttp.ClientSession(headers=headers) as session:
        oembed_url = f"https://oembed.tidal.com/v1.0/endpoint?url={quote(url)}"
        try:
            async with session.get(oembed_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    title = data.get("title", "")
                    author = data.get("author_name", "")
                    media_type = "album" if "/album/" in url else "track"
                    return {
                        "title": title,
                        "artist": author,
                        "type": media_type,
                        "source_url": url,
                    }
        except Exception as e:
            logger.warning(f"Tidal oEmbed error: {e}")
        return None


async def resolve_cross_platform_link(url: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Resolves a Spotify, YouTube, or Tidal URL to an official Apple Music track or album URL.
    Returns (apple_music_url, metadata_dict) or (None, None).
    """
    info = is_cross_platform_url(url)
    if not info:
        return None, None

    platform, media_type = info
    extracted = None

    if platform == "spotify":
        extracted = await extract_spotify_metadata(url)
    elif platform == "youtube":
        extracted = await extract_youtube_metadata(url)
    elif platform == "tidal":
        extracted = await extract_tidal_metadata(url)

    if not extracted or not extracted.get("title"):
        logger.warning(f"Could not extract metadata from {platform} link: {url}")
        return None, None

    title = extracted.get("title", "").strip()
    artist = extracted.get("artist", "").strip()
    m_type = extracted.get("type", "track")

    logger.info(f"Cross-platform match query: Title='{title}', Artist='{artist}', Type='{m_type}'")

    # Search Apple Music API catalog
    try:
        api = await gamdlHelpUrl.get_api()
        search_query = f"{title} {artist}".strip()
        raw_res = await api.get_search_results(search_query, limit=10)
        results = raw_res.get("results", {}) if isinstance(raw_res, dict) else {}

        if m_type == "album":
            albums = results.get("albums", {}).get("data", [])
            if albums:
                first_alb = albums[0]
                alb_attrs = first_alb.get("attributes", {})
                alb_url = alb_attrs.get("url")
                if alb_url:
                    extracted["apple_music_url"] = alb_url
                    extracted["matched_title"] = alb_attrs.get("name")
                    extracted["matched_artist"] = alb_attrs.get("artistName")
                    return alb_url, extracted

        # Default to song match
        songs = results.get("songs", {}).get("data", [])
        if songs:
            first_song = songs[0]
            song_attrs = first_song.get("attributes", {})
            song_url = song_attrs.get("url")
            if song_url:
                extracted["apple_music_url"] = song_url
                extracted["matched_title"] = song_attrs.get("name")
                extracted["matched_artist"] = song_attrs.get("artistName")
                extracted["matched_album"] = song_attrs.get("albumName")
                return song_url, extracted

    except Exception as e:
        logger.error(f"Error querying Apple Music API for cross-platform match: {e}")

    return None, extracted
