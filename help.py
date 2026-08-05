import re
import html
import httpx
from aiogram import Router, types
from aiogram.filters import Command, CommandObject
from aiogram.enums import ParseMode
from aiogram.types import BufferedInputFile

from gamdlHelpUrl import get_url_metadata

help_router = Router()


def escape_html(text: str) -> str:
    """
    Safely escapes HTML special characters.
    """
    if text is None:
        return ""
    return html.escape(str(text))


@help_router.message(Command("help"))
async def help_command(msg: types.Message, command: CommandObject) -> None:
    """
    Handles /help command.
    - If no URL provided: displays bot usage instructions.
    - If URL provided (/help <url>): fetches and displays track, album, or artist details and metadata.
    """
    url = (command.args or "").strip()

    if not url:
        help_text = (
            "<b>ℹ️ Apple Music Downloader - Help & Info</b>\n\n"
            "<b>Commands & Usage:</b>\n"
            "• <code>/help &lt;Apple Music URL&gt;</code> - Get detailed metadata, artwork, audio format support (ALAC/AAC/Atmos), and copyable track/album URLs.\n"
            "• <code>/aac &lt;Apple Music URL&gt;</code> - Download AAC 256kbps audio format.\n"
            "• <code>/atmos &lt;Apple Music URL&gt;</code> - Download Spatial Audio / Dolby Atmos.\n"
            "• <code>/artist &lt;Artist URL&gt;</code> - Browse and select artist albums/singles.\n\n"
            "<b>Metadata Examples:</b>\n"
            "• <b>Song:</b> <code>/help https://music.apple.com/us/album/song-name/123456789?i=987654321</code>\n"
            "• <b>Album:</b> <code>/help https://music.apple.com/us/album/album-name/123456789</code>\n"
            "• <b>Artist:</b> <code>/help https://music.apple.com/us/artist/artist-name/123456789</code>"
        )
        try:
            await msg.answer(help_text, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return

    # Validate URL regex
    if not re.search(r"https?://\S+", url):
        try:
            await msg.answer("❌ Invalid URL. Please provide a valid Apple Music link.\nExample: <code>/help https://music.apple.com/...</code>", parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return

    status_msg = await msg.answer("🔍 Fetching details and metadata...")

    try:
        meta = await get_url_metadata(url)
    except Exception as e:
        try:
            await status_msg.edit_text(f"❌ Failed to fetch metadata: {escape_html(str(e))}", parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return

    m_type = meta.get("type")

    if m_type == "song":
        explicit_tag = " 🔞" if meta.get("is_explicit") else ""
        genres = ", ".join(meta.get("genres", [])) if meta.get("genres") else "N/A"
        track_no = meta.get("track_number")
        disc_no = meta.get("disc_number")
        track_info = f"{track_no}" if track_no else "N/A"
        if disc_no and disc_no > 1:
            track_info += f" (Disc {disc_no})"

        formats_info = meta.get("formats_info", {})
        formats_text = formats_info.get("formats_text", "• Standard Audio")

        song_url = meta.get('url', '')

        text = (
            f"🎵 <b>TRACK DETAILS & METADATA</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Title:</b> {escape_html(meta.get('title'))}{explicit_tag}\n"
            f"• <b>Artist:</b> {escape_html(meta.get('artist'))}\n"
            f"• <b>Album:</b> {escape_html(meta.get('album'))}\n"
            f"• <b>Track No:</b> {track_info}\n"
            f"• <b>Duration:</b> {escape_html(meta.get('duration'))}\n"
            f"• <b>Release Date:</b> {escape_html(meta.get('release_date'))}\n"
            f"• <b>Genre:</b> {escape_html(genres)}\n"
            f"• <b>Composer:</b> {escape_html(meta.get('composer'))}\n"
            f"• <b>ISRC:</b> <code>{escape_html(meta.get('isrc'))}</code>\n"
            f"• <b>Song ID:</b> <code>{escape_html(meta.get('song_id'))}</code>\n"
            f"• <b>Album ID:</b> <code>{escape_html(meta.get('album_id'))}</code>\n"
            f"• <b>Storefront:</b> <code>{escape_html(meta.get('storefront', '').upper())}</code>\n"
            f"• <b>Copyright:</b> {escape_html(meta.get('copyright'))}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎧 <b>AUDIO TECHNICAL DETAILS & FORMATS:</b>\n{formats_text}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <b>Track URL (tap to copy):</b>\n<code>{escape_html(song_url)}</code>"
        )

    elif m_type == "album":
        explicit_tag = " 🔞" if meta.get("is_explicit") else ""
        genres = ", ".join(meta.get("genres", [])) if meta.get("genres") else "N/A"

        formats_info = meta.get("formats_info", {})
        formats_text = formats_info.get("formats_text", "• Standard Audio")

        tracks_lines = []
        tracks = meta.get("tracks", [])
        max_display = 25
        for i, t in enumerate(tracks[:max_display], 1):
            t_explicit = " 🔞" if t.get("is_explicit") else ""
            t_url = t.get('url', '')
            url_code_block = f"\n   🔗 <code>{escape_html(t_url)}</code>" if t_url else ""
            tracks_lines.append(
                f"{i}. <b>{escape_html(t.get('title'))}</b>{t_explicit} ({t.get('duration')}) - <code>{t.get('isrc')}</code>"
                f"{url_code_block}"
            )

        if len(tracks) > max_display:
            tracks_lines.append(f"<i>... and {len(tracks) - max_display} more track(s)</i>")

        tracklist_str = "\n\n".join(tracks_lines) if tracks_lines else "No tracks available"
        album_url = meta.get('url', '')

        text = (
            f"💿 <b>ALBUM DETAILS & METADATA</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Album Title:</b> {escape_html(meta.get('title'))}{explicit_tag}\n"
            f"• <b>Artist:</b> {escape_html(meta.get('artist'))}\n"
            f"• <b>Total Tracks:</b> {meta.get('track_count')}\n"
            f"• <b>Release Date:</b> {escape_html(meta.get('release_date'))}\n"
            f"• <b>Genre:</b> {escape_html(genres)}\n"
            f"• <b>Record Label:</b> {escape_html(meta.get('record_label'))}\n"
            f"• <b>Album ID:</b> <code>{escape_html(meta.get('album_id'))}</code>\n"
            f"• <b>UPC:</b> <code>{escape_html(meta.get('upc'))}</code>\n"
            f"• <b>Storefront:</b> <code>{escape_html(meta.get('storefront', '').upper())}</code>\n"
            f"• <b>Copyright:</b> {escape_html(meta.get('copyright'))}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎧 <b>AUDIO TECHNICAL DETAILS & FORMATS:</b>\n{formats_text}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <b>Album URL (tap to copy):</b>\n<code>{escape_html(album_url)}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📜 <b>TRACKLIST:</b>\n\n{tracklist_str}"
        )

    elif m_type == "artist":
        genres = ", ".join(meta.get("genres", [])) if meta.get("genres") else "N/A"
        artist_url = meta.get('url', '')

        categories = meta.get("categories", {})
        cat_sections = []

        for cat_name, items in categories.items():
            if not items:
                continue
            lines = []
            max_display = 15
            for i, item in enumerate(items[:max_display], 1):
                item_name = escape_html(item.get("name"))
                rel_date = escape_html(item.get("release_date", "N/A"))
                item_url = item.get("url", "")
                url_code = f"\n   🔗 <code>{escape_html(item_url)}</code>" if item_url else ""
                lines.append(f"{i}. <b>{item_name}</b> ({rel_date}){url_code}")

            if len(items) > max_display:
                lines.append(f"<i>... and {len(items) - max_display} more items</i>")

            section_str = "\n\n".join(lines)
            cat_sections.append(f"<b>{cat_name.upper()} ({len(items)}):</b>\n{section_str}")

        all_cats_str = "\n\n━━━━━━━━━━━━━━━━━━━━━━\n\n".join(cat_sections) if cat_sections else "No albums listed."

        text = (
            f"👤 <b>ARTIST DETAILS & CATALOG</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Artist Name:</b> {escape_html(meta.get('name'))}\n"
            f"• <b>Genre:</b> {escape_html(genres)}\n"
            f"• <b>Artist ID:</b> <code>{escape_html(meta.get('artist_id'))}</code>\n"
            f"• <b>Storefront:</b> <code>{escape_html(meta.get('storefront', '').upper())}</code>\n"
            f"🔗 <b>Artist URL (tap to copy):</b>\n<code>{escape_html(artist_url)}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{all_cats_str}"
        )

    elif m_type == "playlist":
        tracks_lines = []
        tracks = meta.get("tracks", [])
        max_display = 25
        for i, t in enumerate(tracks[:max_display], 1):
            t_url = t.get('url', '')
            url_code = f"\n   🔗 <code>{escape_html(t_url)}</code>" if t_url else ""
            tracks_lines.append(f"{i}. <b>{escape_html(t.get('title'))}</b> - {escape_html(t.get('artist'))} ({t.get('duration')}){url_code}")

        if len(tracks) > max_display:
            tracks_lines.append(f"<i>... and {len(tracks) - max_display} more track(s)</i>")

        tracklist_str = "\n\n".join(tracks_lines) if tracks_lines else "No tracks available"
        desc = f"\n• <b>Description:</b> {escape_html(meta.get('description'))}" if meta.get("description") else ""
        playlist_url = meta.get('url', '')

        text = (
            f"📋 <b>PLAYLIST DETAILS & METADATA</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Playlist Name:</b> {escape_html(meta.get('title'))}\n"
            f"• <b>Curator:</b> {escape_html(meta.get('curator'))}\n"
            f"• <b>Total Tracks:</b> {meta.get('track_count')}{desc}\n"
            f"• <b>Playlist ID:</b> <code>{escape_html(meta.get('playlist_id'))}</code>\n"
            f"• <b>Storefront:</b> <code>{escape_html(meta.get('storefront', '').upper())}</code>\n"
            f"🔗 <b>Playlist URL (tap to copy):</b>\n<code>{escape_html(playlist_url)}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>📜 TRACK PREVIEW:</b>\n\n{tracklist_str}"
        )

    else:
        text = f"ℹ️ <b>Metadata:</b>\n{escape_html(str(meta))}"

    artwork_url = meta.get("artwork")
    animated_artwork = meta.get("animated_artwork")

    # Clean up status message
    try:
        await status_msg.delete()
    except Exception:
        pass

    media_sent = False

    # 1. Send main static artwork photo with metadata card instantly (0.1s fast response)
    photo_sent = False
    if artwork_url:
        try:
            if len(text) <= 950:
                await msg.answer_photo(photo=artwork_url, caption=text, parse_mode=ParseMode.HTML)
                photo_sent = True
            else:
                await msg.answer_photo(
                    photo=artwork_url,
                    caption=f"📸 <b>{escape_html(meta.get('title', meta.get('name', 'Cover')))}</b>",
                    parse_mode=ParseMode.HTML
                )
                photo_sent = True
                await msg.answer(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception:
            photo_sent = False

    if not photo_sent:
        try:
            await msg.answer(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception:
            chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
            for chunk in chunks:
                try:
                    await msg.answer(chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                except Exception:
                    pass

    # 2. If Animated Artwork (Motion Cover) is available, send looping video animation follow-up
    if animated_artwork:
        try:
            headers = {"User-Agent": "iTunes/12.11.0.26 (Windows; Microsoft Windows 10 x64) AppleWebKit/537.36"}
            async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=5.0) as client:
                res = await client.get(animated_artwork)
                if res.status_code == 200 and len(res.content) > 0:
                    input_file = BufferedInputFile(res.content, filename="motion_cover.mp4")
                    await msg.answer_animation(
                        animation=input_file,
                        caption=f"🎥 <b>{escape_html(meta.get('title', meta.get('name', 'Animated Cover')))} (Motion Cover)</b>",
                        parse_mode=ParseMode.HTML
                    )
        except Exception:
            pass

