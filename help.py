import re
import html
from aiogram import Router, types
from aiogram.filters import Command, CommandObject
from aiogram.enums import ParseMode

from gamdlHelpUrl import get_url_metadata

help_router = Router()


def escape_html(text: str) -> str:
    """
    Safely escapes HTML special characters.
    """
    if text is None:
        return ""
    return html.escape(str(text))


from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_help_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="Web Vault (stream.eepy.in)", url="https://stream.eepy.in/")],
        [InlineKeyboardButton(text="Join Discord Community", url="https://discord.gg/KBy2UMfjx8")],
        [InlineKeyboardButton(text="Apple Music Storefront Search", url="https://am-l.eepy.in/")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


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
            "<b>Apple Music Downloader - Help & Info</b>\n\n"
            "<b>Commands & Usage:</b>\n"
            "• <code>/help &lt;Apple Music URL&gt;</code> - Get detailed metadata, artwork, audio format support (ALAC/AAC/Atmos), and copyable track/album URLs.\n"
            "• <code>/aac &lt;Apple Music URL&gt;</code> - Download AAC 256kbps audio format.\n"
            "• <code>/atmos &lt;Apple Music URL&gt;</code> - Download Spatial Audio / Dolby Atmos.\n"
            "• <code>/mv &lt;Apple Music URL&gt;</code> - Download Music Video in H.265 / H.264 HD video format.\n"
            "• <code>/artist &lt;Artist URL&gt;</code> - Browse and select artist albums/singles.\n"
            "• <code>/info</code> - View your download statistics, format breakdown, and remaining limits.\n\n"

            "<b>Metadata Examples:</b>\n"
            "• <b>Song:</b> <code>/help https://music.apple.com/us/album/song-name/123456789?i=987654321</code>\n"
            "• <b>Album:</b> <code>/help https://music.apple.com/us/album/album-name/123456789</code>\n"
            "• <b>Artist:</b> <code>/help https://music.apple.com/us/artist/artist-name/123456789</code>"
        )
        try:
            await msg.answer(help_text, parse_mode=ParseMode.HTML, reply_markup=get_help_keyboard())
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
        explicit_tag = " (Explicit)" if meta.get("is_explicit") else ""
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
            f"<b>TRACK DETAILS & METADATA</b>\n"
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
            f"<b>AUDIO TECHNICAL DETAILS & FORMATS:</b>\n{formats_text}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Track URL (tap to copy):</b>\n<code>{escape_html(song_url)}</code>"
        )

    elif m_type == "album":
        explicit_tag = " (Explicit)" if meta.get("is_explicit") else ""
        genres = ", ".join(meta.get("genres", [])) if meta.get("genres") else "N/A"

        formats_info = meta.get("formats_info", {})
        formats_text = formats_info.get("formats_text", "• Standard Audio")

        tracks_lines = []
        tracks = meta.get("tracks", [])
        max_display = 25
        for i, t in enumerate(tracks[:max_display], 1):
            t_explicit = " (Explicit)" if t.get("is_explicit") else ""
            t_url = t.get('url', '')
            url_code_block = f"\n   <code>{escape_html(t_url)}</code>" if t_url else ""
            tracks_lines.append(
                f"{i}. <b>{escape_html(t.get('title'))}</b>{t_explicit} ({t.get('duration')}) - <code>{t.get('isrc')}</code>"
                f"{url_code_block}"
            )

        if len(tracks) > max_display:
            tracks_lines.append(f"<i>... and {len(tracks) - max_display} more track(s)</i>")

        tracklist_str = "\n\n".join(tracks_lines) if tracks_lines else "No tracks available"
        album_url = meta.get('url', '')

        text = (
            f"<b>ALBUM DETAILS & METADATA</b>\n"
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
            f"<b>AUDIO TECHNICAL DETAILS & FORMATS:</b>\n{formats_text}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Album URL (tap to copy):</b>\n<code>{escape_html(album_url)}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>TRACKLIST:</b>\n\n{tracklist_str}"
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
                url_code = f"\n   <code>{escape_html(item_url)}</code>" if item_url else ""
                lines.append(f"{i}. <b>{item_name}</b> ({rel_date}){url_code}")

            if len(items) > max_display:
                lines.append(f"<i>... and {len(items) - max_display} more items</i>")

            section_str = "\n\n".join(lines)
            cat_sections.append(f"<b>{cat_name.upper()} ({len(items)}):</b>\n{section_str}")

        all_cats_str = "\n\n━━━━━━━━━━━━━━━━━━━━━━\n\n".join(cat_sections) if cat_sections else "No albums listed."

        text = (
            f"<b>ARTIST DETAILS & CATALOG</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Artist Name:</b> {escape_html(meta.get('name'))}\n"
            f"• <b>Genre:</b> {escape_html(genres)}\n"
            f"• <b>Artist ID:</b> <code>{escape_html(meta.get('artist_id'))}</code>\n"
            f"• <b>Storefront:</b> <code>{escape_html(meta.get('storefront', '').upper())}</code>\n"
            f"<b>Artist URL (tap to copy):</b>\n<code>{escape_html(artist_url)}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{all_cats_str}"
        )

    elif m_type == "playlist":
        tracks_lines = []
        tracks = meta.get("tracks", [])
        max_display = 25
        for i, t in enumerate(tracks[:max_display], 1):
            t_url = t.get('url', '')
            url_code = f"\n   <code>{escape_html(t_url)}</code>" if t_url else ""
            tracks_lines.append(f"{i}. <b>{escape_html(t.get('title'))}</b> - {escape_html(t.get('artist'))} ({t.get('duration')}){url_code}")

        if len(tracks) > max_display:
            tracks_lines.append(f"<i>... and {len(tracks) - max_display} more track(s)</i>")

        tracklist_str = "\n\n".join(tracks_lines) if tracks_lines else "No tracks available"
        desc = f"\n• <b>Description:</b> {escape_html(meta.get('description'))}" if meta.get("description") else ""
        playlist_url = meta.get('url', '')

        text = (
            f"<b>PLAYLIST DETAILS & METADATA</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Playlist Name:</b> {escape_html(meta.get('title'))}\n"
            f"• <b>Curator:</b> {escape_html(meta.get('curator'))}\n"
            f"• <b>Total Tracks:</b> {meta.get('track_count')}{desc}\n"
            f"• <b>Playlist ID:</b> <code>{escape_html(meta.get('playlist_id'))}</code>\n"
            f"• <b>Storefront:</b> <code>{escape_html(meta.get('storefront', '').upper())}</code>\n"
            f"<b>Playlist URL (tap to copy):</b>\n<code>{escape_html(playlist_url)}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>TRACK PREVIEW:</b>\n\n{tracklist_str}"
        )

    else:
        text = f"<b>Metadata:</b>\n{escape_html(str(meta))}"

    artwork_url = meta.get("artwork")

    # Clean up status message
    try:
        await status_msg.delete()
    except Exception:
        pass

    # Send main image on top (if artwork available)
    if artwork_url:
        try:
            # If text is concise <= 950 chars, send photo with caption directly
            if len(text) <= 950:
                await msg.answer_photo(photo=artwork_url, caption=text, parse_mode=ParseMode.HTML)
                return
            else:
                # For long texts (e.g. albums/artists with tracklists/catalogs), send main photo first then text message
                await msg.answer_photo(photo=artwork_url, caption=f"<b>{escape_html(meta.get('title', meta.get('name', 'Cover')))}</b>", parse_mode=ParseMode.HTML)
        except Exception:
            pass

    # Send detailed text message with copyable URLs
    try:
        await msg.answer(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        # Fallback if text is somehow extremely long
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            try:
                await msg.answer(chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            except Exception:
                pass


def human_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.2f} TB"


@help_router.message(Command("info"))
async def info_command(msg: types.Message) -> None:
    """
    Handles the /info command to display user statistics, downloads, and format breakdown.
    """
    from database import User, async_session
    from sqlmodel import select
    import crud

    user_id = msg.from_user.id
    
    async with async_session() as session:
        # Get or create user
        statement = select(User).where(User.user_id == user_id)
        result = await session.exec(statement)
        user = result.first()
        
        if not user:
            user = User(user_id=user_id)
            session.add(user)
            await session.commit()
            await session.refresh(user)

        stats = await crud.get_user_download_stats(session, user_id)
        alac_12h_count = await crud.get_alac_download_count_12h(session, user_id)

    status_badge = "<b>Premium User</b>" if user.is_premium else "<b>Standard User</b>"
    
    # Calculate limits text
    if user.is_premium:
        mv_limit_text = "Unlimited"
        alac_limit_text = "Unlimited"
    else:
        mv_limit_text = f"<code>{user.downloaded_today} / 50</code> vids/day"
        alac_limit_text = f"<code>{alac_12h_count} / 100</code> tracks/12h"

    total_delivered = stats["cached_count"] + stats["uncached_count"]
    
    # Alerts or suggestions based on limit
    limit_warning = " (Limit reached)" if not user.is_premium and alac_12h_count >= 100 else ""

    info_text = (
        f"<b>YOUR DOWNLOAD DASHBOARD & INFO</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Account Details:</b>\n"
        f"• <b>User ID:</b> <code>{user_id}</code>\n"
        f"• <b>Status:</b> {status_badge}\n"
        f"• <b>Music Video Limit:</b> {mv_limit_text}\n"
        f"• <b>AAC & Dolby Atmos:</b> Unlimited\n\n"
        
        f"<b>ALAC Lossless Limit:</b>\n"
        f"• <b>Downloads (Last 12h):</b> {alac_limit_text}{limit_warning}\n\n"
        
        f"<b>Download Statistics:</b>\n"
        f"• <b>Total Tracks Delivered:</b> <code>{total_delivered}</code>\n"
        f"  ├ <i>Downloaded:</i> <code>{stats['uncached_count']}</code>\n"
        f"  └ <i>From Cache:</i> <code>{stats['cached_count']}</code>\n"
        f"• <b>Total Data Transferred:</b> <code>{human_size(stats['total_size'])}</code>\n"
        f"• <b>Total Cache Saved:</b> <code>{human_size(stats['total_delivered_size'] - stats['total_size'])}</code>\n\n"
        
        f"<b>Format Breakdown:</b>\n"
        f"• <b>ALAC (Lossless):</b> <code>{stats['alac_count']}</code>\n"
        f"• <b>AAC (High Quality):</b> <code>{stats['aac_count']}</code>\n"
        f"• <b>Dolby Atmos (Spatial):</b> <code>{stats['atmos_count']}</code>\n"
        f"• <b>Music Videos:</b> <code>{stats['mv_count']}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    try:
        await msg.answer(info_text, parse_mode=ParseMode.HTML)
    except Exception as e:
        print(f"Failed to send /info command response: {e}")
