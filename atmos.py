import asyncio
import glob
import html
import os
import re
import shutil
from datetime import datetime, timezone

from aiogram import Router, types
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, FSInputFile
from sqlmodel import select

import utils
import schema
import crud
import database
from database import User, async_session
from gamdlUrl import get_any_url, normalize_apple_music_url
from gamdl.interface import AppleMusicInterface
import time
from queues import atmos_queue, atmos_in_queue, atmos_pending_jobs, atmos_locks, is_user_busy, active_tasks, pending_album_prompts
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.markdown import hbold, hcode
import bot_control
import audio_service

atmos = Router()

@atmos.message(Command("atmos"))
async def atmos_download(msg: types.Message, command: CommandObject) -> None:
    raw_args = (command.args or "").strip()
    url, no_cache = utils.extract_no_cache_flag(raw_args)

    if not re.fullmatch(r"https?://\S+", url):
        try:
            await msg.answer("Usage:\n/atmos &lt;Apple Music URL&gt; [-n]")
        except Exception:
            pass
        return

    user_id_local = msg.from_user.id
    if is_user_busy(user_id_local):
        try:
            await msg.answer("⏳ You already have a download in progress. Please wait until it's finished.")
        except Exception:
            pass
        return

    norm_url = normalize_apple_music_url(url)
    try:
        url_info = AppleMusicInterface.get_url_info(norm_url)
    except Exception:
        url_info = None

    # If it's a full album, present delivery options prompt
    if url_info and url_info.type == "album" and not url_info.sub_id:
        status_msg = await msg.answer("🔍 Fetching Dolby Atmos album information...")
        try:
            songs = await get_any_url(norm_url)
        except Exception as e:
            try:
                await status_msg.edit_text("❌ Unable to fetch album details. Please check the link or try again later.")
            except Exception:
                pass
            return

        if not songs:
            try:
                await status_msg.edit_text("❌ No tracks found for this album.")
            except Exception:
                pass
            return

        has_atmos = any(
            any(t in (s.audio_traits or []) for t in ("atmos", "spatial"))
            for s in songs
        )
        if not has_atmos:
            try:
                await status_msg.edit_text(
                    "⚠️ <b>Dolby Atmos is not available</b> for this album on Apple Music.\n\n"
                    "👉 Send the link directly for Lossless ALAC or use <code>/aac &lt;link&gt;</code> for AAC 256kbps.",
                    parse_mode="HTML"
                )
            except Exception:
                pass
            return

        album_id = url_info.id
        album_title = songs[0].album or "Album"
        artist = songs[0].artist or "Unknown Artist"
        track_count = len(songs)

        prompt_key = f"{user_id_local}_{album_id}_atmos{'_nc' if no_cache else ''}"
        pending_album_prompts[prompt_key] = {
            "url": norm_url,
            "songs": songs,
            "msg": msg,
            "user_id": user_id_local,
            "format": "atmos",
            "album_id": album_id,
            "album_title": album_title,
            "artist": artist,
            "no_cache": no_cache,
        }

        kb = InlineKeyboardBuilder()
        kb.row(
            types.InlineKeyboardButton(text="🎵 Individual Tracks", callback_data=f"alb_mode:tracks:{prompt_key}"),
            types.InlineKeyboardButton(text="📦 ZIP Archive Only", callback_data=f"alb_mode:zip:{prompt_key}")
        )
        kb.row(
            types.InlineKeyboardButton(text="💿 Tracks + ZIP", callback_data=f"alb_mode:both:{prompt_key}"),
            types.InlineKeyboardButton(text="✖ Cancel", callback_data=f"alb_mode:cancel:{prompt_key}")
        )

        cache_line = "\n⚡ <b>Cache:</b> Disabled (Fresh Download)" if no_cache else ""
        prompt_text = (
            f"💿 <b>Album:</b> {hcode(album_title)}\n"
            f"👤 <b>Artist:</b> {hcode(artist)}\n"
            f"🎵 <b>Tracks:</b> {track_count} track(s)\n"
            f"🎛 <b>Format:</b> Dolby Atmos{cache_line}\n\n"
            f"<b>Please choose delivery option:</b>"
        )
        try:
            await status_msg.edit_text(prompt_text, reply_markup=kb.as_markup(), parse_mode="HTML")
        except Exception:
            pass
        return

    # Mark user busy immediately for single track
    atmos_in_queue.add(user_id_local)

    # Fetch metadata to see how many tracks
    status_msg = await msg.answer("🔍 Fetching Dolby Atmos metadata...")
    try:
        songs = await get_any_url(norm_url)
    except Exception as e:
        atmos_in_queue.discard(user_id_local)
        try:
            await status_msg.edit_text("❌ Unable to fetch track details. Please check the link or try again later.")
        except Exception:
            pass
        return

    if not songs:
        atmos_in_queue.discard(user_id_local)
        try:
            await status_msg.edit_text("❌ No tracks found.")
        except Exception:
            pass
        return

    # Check if Dolby Atmos is supported for this track/album
    has_atmos = any(
        any(t in (s.audio_traits or []) for t in ("atmos", "spatial"))
        for s in songs
    )
    if not has_atmos:
        atmos_in_queue.discard(user_id_local)
        try:
            await status_msg.edit_text(
                "⚠️ <b>Dolby Atmos is not available</b> for this track/album on Apple Music.\n\n"
                "👉 Send the link directly for Lossless ALAC or use <code>/aac &lt;link&gt;</code> for AAC 256kbps.",
                parse_mode="HTML"
            )
        except Exception:
            pass
        return

    # Check database for existing Atmos cached tracks
    if not no_cache:
        file_ids, tracks_to_download = await crud.check_db_for_urls(songs, format_type="atmos")
    else:
        file_ids, tracks_to_download = [], [str(s.url) for s in songs if s.url]

    for file_id in file_ids:
        try:
            sent_msg = await msg.answer_audio(audio=file_id)
        except Exception:
            sent_msg = None
        if sent_msg:
            async with async_session() as session:
                result = await session.exec(select(User).where(User.user_id == user_id_local))
                user = result.first()
                if user:
                    user.download_count += 1
                    session.add(user)
                    await session.commit()
                    
                    # Log cached delivery
                    try:
                        db_track = (await session.exec(select(database.AtmosTracks).where(database.AtmosTracks.file_id == file_id))).first()
                        song_id_val = db_track.song_id if db_track else None
                        size_val = db_track.size if db_track else 0
                        await crud.log_download(
                            session=session,
                            user_id=user_id_local,
                            song_id=song_id_val,
                            format_type="atmos",
                            size=size_val,
                            is_cached=True
                        )
                        await session.commit()
                    except Exception as le:
                        print(f"Failed to log cached Atmos download: {le}")

    if not tracks_to_download:
        atmos_in_queue.discard(user_id_local)
        try:
            await status_msg.edit_text("✅ All Dolby Atmos tracks delivered from cache!")
        except Exception:
            pass
        return

    # Queue the missing tracks
    atmos_pending_jobs[user_id_local] = len(tracks_to_download)
    position = atmos_queue.qsize()
    
    try:
        await status_msg.edit_text(f"Queued {len(tracks_to_download)} Dolby Atmos track(s) (starting at position {position + 1}).")
    except Exception:
        pass

    for track_url in tracks_to_download:
        await atmos_queue.put({
            "url": track_url,
            "songs": songs,
            "msg": msg,
            "user_id": user_id_local,
            "status_msg": status_msg,
            "download_mode": "tracks",
            "no_cache": no_cache,
        })


async def deliver_single_atmos_track(
    file_path: str,
    msg: Optional[Message],
    songs: list,
    user_id_local: int,
    download_mode: str,
) -> None:
    async with async_session() as session:
        result = await session.exec(select(User).where(User.user_id == user_id_local))
        user = result.first()

        track_title, artist, thumbnail, duration, isrc = await asyncio.to_thread(
            utils.extract_track_metadata, file_path
        )

        sent_msg = None
        saved_chat_id = utils.STORAGE_CHANNEL_ID
        saved_message_id = None
        if msg:
            sent_msg, saved_chat_id, saved_message_id = await utils.upload_and_deliver_audio(
                bot=msg.bot,
                user_chat_id=msg.chat.id,
                file_path=file_path,
                title=track_title,
                performer=artist,
                thumbnail=thumbnail,
                duration=duration
            )

        if sent_msg and user:
            user.download_count += 1
            session.add(user)
            await session.commit()

        media_obj = (sent_msg.audio or sent_msg.document) if sent_msg else None
        file_id_val = media_obj.file_id if media_obj else None
        file_uniq_val = media_obj.file_unique_id if media_obj else None
        file_sz_val = getattr(media_obj, "file_size", 0) if media_obj else (os.path.getsize(file_path) if os.path.exists(file_path) else 0)

        tbot = schema.TrackInputSchema(
            file_id=file_id_val,
            file_unique_id=file_uniq_val,
            title=track_title,
            size=file_sz_val,
            isrc=isrc,
            chat_id=saved_chat_id,
            message_id=saved_message_id
        )

        matched = False
        if isrc and songs:
            for original_track in songs:
                if original_track.isrc == isrc:
                    track_input = schema.TrackInputSchema(**original_track.model_dump())
                    track_input.file_id = tbot.file_id
                    track_input.file_unique_id = tbot.file_unique_id
                    track_input.size = tbot.size
                    track_input.chat_id = tbot.chat_id
                    track_input.message_id = tbot.message_id
                    await crud.save_single_track(session=session, track_data=track_input, format_type="atmos")
                    await session.commit()
                    
                    try:
                        await crud.log_download(
                            session=session,
                            user_id=user_id_local,
                            song_id=track_input.song_id,
                            format_type="atmos",
                            size=tbot.size,
                            is_cached=False
                        )
                        await session.commit()
                    except Exception as le:
                        print(f"Failed to log Atmos download history: {le}")
                        
                    matched = True
                    break

        if not matched and songs:
            for original_track in songs:
                if utils.convert_text(original_track.title) == utils.convert_text(tbot.title):
                    track_input = schema.TrackInputSchema(**original_track.model_dump())
                    track_input.file_id = tbot.file_id
                    track_input.file_unique_id = tbot.file_unique_id
                    track_input.size = tbot.size
                    track_input.chat_id = tbot.chat_id
                    track_input.message_id = tbot.message_id
                    await crud.save_single_track(session=session, track_data=track_input, format_type="atmos")
                    await session.commit()
                    
                    try:
                        await crud.log_download(
                            session=session,
                            user_id=user_id_local,
                            song_id=track_input.song_id,
                            format_type="atmos",
                            size=tbot.size,
                            is_cached=False
                        )
                        await session.commit()
                    except Exception as le:
                        print(f"Failed to log Atmos download history: {le}")
                        
                    break

        if download_mode == "tracks":
            try:
                await asyncio.to_thread(os.remove, file_path)
            except Exception as e:
                print(f"Failed to remove file {file_path}: {e}")


async def process_atmos_download(task: dict) -> None:
    import secrets
    track_url = task.get("url")
    songs = task.get("songs")
    msg: Optional[Message] = task.get("msg")
    user_id_local = task.get("user_id", 999999999)
    status_msg = task.get("status_msg")
    download_mode = task.get("download_mode", "tracks")
    album_id_task = task.get("album_id")

    if not songs and track_url:
        from gamdlUrl import get_any_url
        try:
            songs = await get_any_url(track_url)
        except Exception:
            songs = []

    if msg and hasattr(msg, "message_id"):
        unique_task_id = f"atmos_{msg.message_id}_{int(asyncio.get_event_loop().time() * 1000)}"
    else:
        unique_task_id = f"atmos_cache_{int(asyncio.get_event_loop().time() * 1000)}_{secrets.token_hex(4)}"

    output_dir = os.path.abspath(os.path.join("downloads", unique_task_id))
    process = None

    track_title = "Dolby Atmos Track"
    artist = "Unknown Artist"
    if songs:
        track_title = songs[0].title
        artist = songs[0].artist
        if len(songs) > 1:
            track_title = songs[0].album or f"{songs[0].title} (+{len(songs)-1} tracks)"

    active_tasks[unique_task_id] = {
        "process": None,
        "cancelled": False,
        "user_id": user_id_local,
        "status_msg": status_msg,
        "track_title": track_title,
        "artist": artist,
        "format": "DOLBY ATMOS",
        "status": "downloading",
        "start_time": time.time(),
        "progress": 0,
    }

    no_cache = task.get("no_cache", False)

    # If ZIP only mode, check DB cache first
    album_id = album_id_task or (songs[0].album_id if songs else None)
    if download_mode == "zip" and album_id and not no_cache:
        async with async_session() as session:
            cached_zip_fid, cached_gofile_url, cached_zip_size = await crud.get_cached_album_zip(session, album_id, format_type="atmos")
            size_line = f"\n💾 <b>Size:</b> {utils.human_size(cached_zip_size)}" if cached_zip_size else ""
            gf_line = f"\n🌐 <b>Fast Download (GoFile):</b> <a href='{cached_gofile_url}'>High-Speed Link</a>" if cached_gofile_url else ""
            gf_markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🌐 Fast Download (GoFile)", url=cached_gofile_url)]]) if cached_gofile_url else None
            delivered = False
            alb_name = songs[0].album or "Album"
            art_name = songs[0].artist or "Unknown Artist"
            esc_alb = html.escape(alb_name)
            esc_art = html.escape(art_name)
            if cached_zip_fid:
                if msg:
                    try:
                        await msg.answer_document(
                            document=cached_zip_fid,
                            caption=f"📦 <b>{esc_alb}</b> (Dolby Atmos)\n👤 <i>{esc_art}</i>{size_line}{gf_line}\n⚡ <i>Delivered from cache</i>",
                            parse_mode="HTML",
                            reply_markup=gf_markup
                        )
                        delivered = True
                    except Exception as e:
                        print(f"Failed to deliver cached Atmos zip document: {e}")
                        try:
                            await msg.answer_document(
                                document=cached_zip_fid,
                                caption=f"📦 {alb_name} (Dolby Atmos)\n👤 {art_name}\n⚡ Delivered from cache",
                                reply_markup=gf_markup
                            )
                            delivered = True
                        except Exception:
                            pass
                if status_msg and delivered:
                    try:
                        await status_msg.edit_text("✅ Dolby Atmos Album ZIP delivered from cache!")
                    except Exception:
                        pass

            if not delivered and cached_gofile_url:
                if msg:
                    try:
                        await msg.answer(
                            f"📦 <b>{esc_alb}</b> (Dolby Atmos)\n"
                            f"👤 <i>{esc_art}</i>{size_line}\n\n"
                            f"⚡ <i>Delivered from cache:</i>\n"
                            f"🌐 <a href='{cached_gofile_url}'><b>Download Album ZIP on GoFile</b></a>",
                            parse_mode="HTML",
                            reply_markup=gf_markup
                        )
                        delivered = True
                    except Exception as e:
                        print(f"Failed to deliver cached Atmos GoFile link: {e}")
                        try:
                            await msg.answer(
                                f"📦 {alb_name} (Dolby Atmos)\n"
                                f"👤 {art_name}{size_line}\n\n"
                                f"⚡ Delivered from cache:\n"
                                f"🌐 Download Album ZIP on GoFile: {cached_gofile_url}",
                                reply_markup=gf_markup
                            )
                            delivered = True
                        except Exception:
                            pass
                if status_msg and delivered:
                    try:
                        await status_msg.edit_text(
                            f"✅ Cached Album ZIP link delivered!\n\n🌐 <a href='{cached_gofile_url}'>Download on GoFile</a>",
                            parse_mode="HTML",
                            reply_markup=gf_markup
                        )
                    except Exception:
                        pass

            if delivered:
                return


    temp_dir = f"{output_dir}_temp"
    try:
        await asyncio.to_thread(os.makedirs, output_dir, exist_ok=True)
        await asyncio.to_thread(os.makedirs, temp_dir, exist_ok=True)

        # Start in-memory downloading with Dolby Atmos


        cookies_path = os.path.abspath("cookies.txt")


        dl_targets = [s.url for s in songs] if (download_mode in ("zip", "both") and songs) else [track_url]



        if unique_task_id in active_tasks:


            active_tasks[unique_task_id]["async_task"] = asyncio.current_task()



        uploaded_files = set()


        completed_atmos_count = 0


        total_atmos_tracks = len(songs) if songs else 1



        async def on_track_downloaded(item, file_path: str):


            nonlocal completed_atmos_count


            if not file_path or not os.path.exists(file_path):


                return


            if file_path in uploaded_files:


                return


            uploaded_files.add(file_path)



            if download_mode == "zip":


                completed_atmos_count += 1


                if status_msg:


                    try:


                        await status_msg.edit_text(f"🚀 Downloading Dolby Atmos album: {completed_atmos_count}/{total_atmos_tracks} track(s)...")


                    except Exception:


                        pass


                return



            await deliver_single_atmos_track(file_path, msg, songs, user_id_local, download_mode)



        try:


            await audio_service.download_audio(


                urls=dl_targets,


                format_type="atmos",


                output_dir=output_dir,


                temp_dir=temp_dir,


                cookies_path=cookies_path,


                on_track_done=on_track_downloaded,


                is_cancelled=lambda: active_tasks.get(unique_task_id, {}).get("cancelled", False),


            )


        except Exception as e:


            err_msg = audio_service.format_gamdl_error(e)


            print(f"🛑 In-memory Atmos download failed for {unique_task_id}: {e}")


            if status_msg and not active_tasks.get(unique_task_id, {}).get("cancelled"):


                try:


                    await status_msg.edit_text(f"❌ Dolby Atmos Download Failed\n\n{err_msg}")


                except Exception:


                    pass


            return

        # Check if task was cancelled while process was terminating
        if active_tasks.get(unique_task_id, {}).get("cancelled"):
            return

        # Handle ZIP packaging for 'zip' and 'both' modes (only if files were downloaded)
        if download_mode in ("zip", "both") and songs and len(uploaded_files) > 0:
            if status_msg:
                try:
                    await status_msg.edit_text("📦 Packaging Dolby Atmos album into ZIP with max-res cover and lyrics (.lrc)...")
                except Exception:
                    pass

            await utils.save_album_cover_and_lyrics(songs, output_dir)

            album_title = songs[0].album or "Album"
            artist = songs[0].artist or "Unknown Artist"
            clean_album = re.sub(r'[\\/*?:"<>|]', "", album_title)
            clean_artist = re.sub(r'[\\/*?:"<>|]', "", artist)
            zip_filename = f"{clean_artist} - {clean_album} [Dolby Atmos].zip"
            zip_path = os.path.join(os.path.dirname(output_dir), zip_filename)

            await utils.create_album_zip(output_dir, zip_path)
            zip_size = os.path.getsize(zip_path) if os.path.exists(zip_path) else 0

            esc_album_title = html.escape(album_title)
            esc_artist = html.escape(artist)

            caption = (
                f"📦 <b>{esc_album_title}</b> (Dolby Atmos)\n"
                f"👤 <i>{esc_artist}</i>\n"
                f"💾 <b>Size:</b> {utils.human_size(zip_size)}\n"
                f"🎵 {len(songs)} Tracks • Max-Res Cover • Lyrics (.lrc)"
            )

            thumb_data = None
            cover_file = os.path.join(output_dir, "Cover.jpg")
            if os.path.exists(cover_file):
                thumb_data = types.FSInputFile(cover_file)

            if msg:
                sent_doc, saved_cid, saved_mid, zip_fid, gofile_url, uploaded_zip_size = await utils.upload_and_deliver_zip_document(
                    bot=msg.bot,
                    user_chat_id=msg.chat.id,
                    file_path=zip_path,
                    caption=caption,
                    thumbnail=thumb_data
                )
            else:
                sent_doc, saved_cid, saved_mid, zip_fid, gofile_url, uploaded_zip_size = None, None, None, None, None, zip_size
            final_zip_size = uploaded_zip_size or zip_size

            alb_id_save = album_id or (songs[0].album_id if songs else None)
            if alb_id_save:
                async with async_session() as session:
                    await crud.save_cached_album_zip(
                        session=session,
                        album_id=alb_id_save,
                        album_name=album_title,
                        artist=artist,
                        format_type="atmos",
                        zip_file_id=zip_fid,
                        gofile_url=gofile_url,
                        zip_size=final_zip_size
                    )

            if gofile_url and not zip_fid and msg:
                try:
                    reason_msg = (
                        "⚡ <i>File size exceeds 2GB Telegram limit. Uploaded to GoFile:</i>\n"
                        if final_zip_size > 2000 * 1024 * 1024
                        else "⚡ <i>Telegram upload failed or skipped. Uploaded to GoFile:</i>\n"
                    )
                    gf_markup = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🌐 Download Album ZIP (GoFile)", url=gofile_url)]
                    ])
                    await msg.answer(
                        f"📦 <b>{esc_album_title}</b> (Dolby Atmos)\n"
                        f"👤 <i>{esc_artist}</i>\n"
                        f"💾 <b>Size:</b> {utils.human_size(final_zip_size)}\n\n"
                        f"{reason_msg}"
                        f"🌐 <a href='{gofile_url}'><b>Download Album ZIP on GoFile</b></a>",
                        parse_mode="HTML",
                        reply_markup=gf_markup
                    )
                except Exception as e:
                    print(f"Failed to send GoFile fallback message: {e}")
                    try:
                        gf_markup = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="🌐 Download Album ZIP (GoFile)", url=gofile_url)]
                        ])
                        await msg.answer(
                            f"📦 {album_title} (Dolby Atmos)\n"
                            f"👤 {artist}\n"
                            f"💾 Size: {utils.human_size(final_zip_size)}\n\n"
                            f"🌐 Download Album ZIP on GoFile: {gofile_url}",
                            reply_markup=gf_markup
                        )
                    except Exception as e2:
                        print(f"Plain text GoFile fallback failed: {e2}")

            if os.path.exists(zip_path):
                try:
                    os.remove(zip_path)
                except Exception:
                    pass

            if status_msg:
                try:
                    gf_markup = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🌐 Download Album ZIP (GoFile)", url=gofile_url)]
                    ]) if gofile_url else None
                    gf_line = f"\n📁 <b>GoFile Download:</b> <a href='{gofile_url}'>High-Speed Link</a>" if gofile_url else ""

                    if len(uploaded_files) < total_atmos_tracks:
                        await status_msg.edit_text(
                            f"⚠️ <b>Partial Dolby Atmos Album Completed:</b> {len(uploaded_files)}/{total_atmos_tracks} tracks packaged.\n"
                            f"Some tracks failed to download from Apple Music.{gf_line}\n\n"
                            f"🌐 Link can also be downloaded at: https://stream.eepy.in/",
                            parse_mode="HTML",
                            reply_markup=gf_markup
                        )
                    else:
                        await status_msg.edit_text(
                            f"✅ Dolby Atmos Album ZIP completed and delivered successfully!{gf_line}\n\n"
                            f"🌐 Link can also be downloaded at: https://stream.eepy.in/",
                            parse_mode="HTML",
                            reply_markup=gf_markup
                        )
                except Exception as e:
                    print(f"Failed to edit status_msg: {e}")
                    try:
                        gf_markup = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="🌐 Download Album ZIP (GoFile)", url=gofile_url)]
                        ]) if gofile_url else None
                        gf_line_plain = f"\n📁 GoFile: {gofile_url}" if gofile_url else ""
                        await status_msg.edit_text(
                            f"✅ Dolby Atmos Album ZIP completed and delivered successfully!{gf_line_plain}\n\n"
                            f"🌐 Link can also be downloaded at: https://stream.eepy.in/",
                            reply_markup=gf_markup
                        )
                    except Exception:
                        pass
            return

        if not active_tasks.get(unique_task_id, {}).get("cancelled"):
            if status_msg:
                if len(uploaded_files) == 0:
                    try:
                        await status_msg.edit_text(
                            "❌ Dolby Atmos Download Failed\n\n"
                            "The requested track or album could not be downloaded in Dolby Atmos from Apple Music.\n\n"
                            "👉 Try downloading with Lossless ALAC or /aac <link>."
                        )
                    except Exception:
                        pass
                elif len(uploaded_files) < total_atmos_tracks:
                    try:
                        await status_msg.edit_text(
                            f"⚠️ <b>Partially Completed:</b> {len(uploaded_files)}/{total_atmos_tracks} Dolby Atmos tracks delivered.\n"
                            f"Some tracks failed to download from Apple Music.\n\n"
                            f"🌐 Downloaded tracks: https://stream.eepy.in/",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
                else:
                    try:
                        await status_msg.edit_text("✅ Dolby Atmos download and upload completed.\n\n🌐 Link can be downloaded at: https://stream.eepy.in/")
                    except Exception:
                        pass

    except Exception as error:
        print(f"Dolby Atmos download error: {error}")
        if status_msg:
            try:
                await status_msg.edit_text("❌ Dolby Atmos download failed. Please try again later.")
            except Exception:
                pass
    finally:
        active_tasks.pop(unique_task_id, None)
        for d_clean in (output_dir, temp_dir):
            if await asyncio.to_thread(os.path.exists, d_clean):
                try:
                    await asyncio.to_thread(shutil.rmtree, d_clean)
                except Exception as e:
                    print(f"Failed to delete {d_clean}: {e}")
        import gc
        gc.collect()


async def _run_atmos_download_task(task: dict) -> None:
    """Executes process_atmos_download in an isolated child task so cancellation never kills the worker."""
    job_task = asyncio.create_task(process_atmos_download(task))
    task["_job_task"] = job_task
    try:
        await job_task
    except asyncio.CancelledError:
        print(f"[Atmos Worker] Download task for {task.get('url')} was cancelled.")
    except Exception as exc:
        print(f"[Atmos Worker] Error processing Atmos download: {exc}")


async def atmos_worker() -> None:
    """
    Worker function to process the atmos download queue. Up to 10 run concurrently.
    Runs continuously and will not crash on download cancellations or errors.
    """
    while True:
        try:
            while bot_control.is_bot_paused:
                await asyncio.sleep(1)

            task = await atmos_queue.get()
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[Atmos Worker] Error fetching from atmos_queue: {e}")
            await asyncio.sleep(1)
            continue

        user_id = task.get("user_id", 999999999)
        msg = task.get("msg")
        is_headless = task.get("is_admin_cache") or (msg is None) or (user_id == 999999999)

        try:
            if is_headless:
                await _run_atmos_download_task(task)
            else:
                user_lock = atmos_locks.setdefault(user_id, asyncio.Lock())
                async with user_lock:
                    await _run_atmos_download_task(task)
        except Exception as lock_err:
            print(f"[Atmos Worker] Error handling user lock in atmos_worker: {lock_err}")
        finally:
            if not is_headless and user_id:
                remaining = atmos_pending_jobs.get(user_id, 1) - 1
                if remaining <= 0:
                    atmos_pending_jobs.pop(user_id, None)
                    atmos_in_queue.discard(user_id)
                    atmos_locks.pop(user_id, None)
                else:
                    atmos_pending_jobs[user_id] = remaining
            try:
                atmos_queue.task_done()
            except Exception:
                pass
