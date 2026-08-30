#!/usr/bin/env python3
"""
PostgreSQL Database Backup & Restore Utility
============================================
Supports:
1. Full SQL / gzip dump via pg_dump
2. Pure Python JSON.gz fallback dump
3. Direct delivery to Telegram Storage Channel / Admin
4. Database restoration from backups
"""

import argparse
import asyncio
import gzip
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()


def get_pg_url() -> str:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL environment variable is missing in .env")
    # Convert asyncpg connection string to standard postgresql://
    return db_url.replace("postgresql+asyncpg://", "postgresql://")


async def dump_via_python_json(output_path: str) -> str:
    """Fallback database dumper using SQLModel/asyncpg when pg_dump is unavailable."""
    from sqlmodel import select
    from database import async_session, Tracks, AACTracks, AtmosTracks, MVTracks, Albums, User, DownloadHistory

    print("Extracting tables via Python...")
    tables_data = {}

    async with async_session() as session:
        models = {
            "albums": Albums,
            "tracks": Tracks,
            "aac_tracks": AACTracks,
            "atmos_tracks": AtmosTracks,
            "mv_tracks": MVTracks,
            "user": User,
            "download_history": DownloadHistory,
        }
        for name, model in models.items():
            result = await session.exec(select(model))
            rows = result.all()
            tables_data[name] = [
                {k: v.isoformat() if hasattr(v, "isoformat") else v for k, v in row.model_dump().items()}
                for row in rows
            ]
            print(f"  - Exported {len(rows)} records from '{name}'")

    with gzip.open(output_path, "wt", encoding="utf-8") as f:
        json.dump(tables_data, f, indent=2)

    return output_path


def dump_via_pg_dump(output_path: str, pg_url: str) -> bool:
    """Dumps PostgreSQL database to a compressed .sql.gz file using pg_dump."""
    if not shutil.which("pg_dump"):
        return False

    print(f"Running pg_dump to {output_path}...")
    try:
        with gzip.open(output_path, "wb") as gz_out:
            proc = subprocess.Popen(
                ["pg_dump", pg_url, "--no-owner", "--no-acl", "--clean", "--if-exists"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = proc.communicate()
            if proc.returncode != 0:
                print(f"pg_dump error: {stderr.decode(errors='ignore')}")
                return False
            gz_out.write(stdout)
        return True
    except Exception as e:
        print(f"pg_dump execution failed: {e}")
        return False


async def upload_to_github_release(file_path: str, timestamp: str) -> Optional[str]:
    """
    Uploads backup archive to a GitHub Release using GitHub REST API.
    """
    import aiohttp

    token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB")
    repo = os.getenv("GITHUB_REPO", "eepyyyy/Telegram_bot")
    if not token:
        print("⚠️ No GITHUB_TOKEN or GITHUB found in .env. Skipping GitHub release upload.")
        return None

    tag_name = f"backup-{timestamp}"
    filename = os.path.basename(file_path)
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Telegram-Bot-DB-Backup"
    }

    create_url = f"https://api.github.com/repos/{repo}/releases"
    release_payload = {
        "tag_name": tag_name,
        "name": f"Database Backup - {timestamp}",
        "body": (
            f"📦 **Automated PostgreSQL Database Backup**\n\n"
            f"- 🕒 **Timestamp:** `{timestamp} UTC`\n"
            f"- 📁 **File:** `{filename}` ({file_size_mb:.2f} MB)\n"
            f"- 🔒 Complete dump of tracks, albums, users, and download history."
        ),
        "draft": false,
        "prerelease": false
    }

    try:
        async with aiohttp.ClientSession() as session:
            print(f"Creating GitHub Release '{tag_name}' in {repo}...")
            async with session.post(create_url, json=release_payload, headers=headers) as resp:
                if resp.status not in (200, 201):
                    err_txt = await resp.text()
                    print(f"❌ Failed to create GitHub release: {resp.status} - {err_txt}")
                    return None
                release_data = await resp.json()

            release_id = release_data.get("id")
            html_url = release_data.get("html_url")
            upload_url = f"https://uploads.github.com/repos/{repo}/releases/{release_id}/assets?name={filename}"

            print(f"Uploading {filename} ({file_size_mb:.2f} MB) to GitHub Release...")
            with open(file_path, "rb") as f:
                file_bytes = f.read()

            upload_headers = {
                **headers,
                "Content-Type": "application/gzip" if filename.endswith(".gz") else "application/octet-stream"
            }
            async with session.post(upload_url, data=file_bytes, headers=upload_headers) as up_resp:
                if up_resp.status not in (200, 201):
                    err_txt = await up_resp.text()
                    print(f"❌ Failed to upload asset to GitHub release: {up_resp.status} - {err_txt}")
                    return html_url
                print(f"✅ Backup successfully published to GitHub: {html_url}")
                return html_url
    except Exception as e:
        print(f"❌ GitHub release upload exception: {e}")
        return None


async def send_to_telegram(file_path: str, caption: str):
    """Sends backup document directly to Telegram Storage Channel or Admin."""
    from aiogram import Bot, types
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    token = os.getenv("TOKEN_API")
    target_chat = os.getenv("STORAGE_CHANNEL_ID") or os.getenv("ADMIN_ID")
    if not token or not target_chat:
        print("⚠️ Telegram token or STORAGE_CHANNEL_ID/ADMIN_ID not configured in .env. Skipping Telegram upload.")
        return

    print(f"Uploading backup to Telegram chat {target_chat}...")
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        with open(file_path, "rb") as f:
            doc = types.BufferedInputFile(f.read(), filename=os.path.basename(file_path))
            await bot.send_document(
                chat_id=target_chat,
                document=doc,
                caption=caption
            )
        print("✅ Backup successfully sent to Telegram!")
    except Exception as e:
        print(f"❌ Failed to upload backup to Telegram: {e}")
    finally:
        await bot.session.close()


async def restore_from_json(file_path: str):
    """Restores database tables from a .json or .json.gz file."""
    from database import async_session, init_db, Tracks, AACTracks, AtmosTracks, MVTracks, Albums, User, DownloadHistory

    await init_db()
    opener = gzip.open if file_path.endswith(".gz") else open
    with opener(file_path, "rt", encoding="utf-8") as f:
        data = json.load(f)

    models = {
        "albums": Albums,
        "tracks": Tracks,
        "aac_tracks": AACTracks,
        "atmos_tracks": AtmosTracks,
        "mv_tracks": MVTracks,
        "user": User,
        "download_history": DownloadHistory,
    }

    async with async_session() as session:
        for name, model in models.items():
            items = data.get(name, [])
            count = 0
            for item in items:
                try:
                    obj = model(**item)
                    await session.merge(obj)
                    count += 1
                except Exception as e:
                    print(f"Error restoring record in {name}: {e}")
            await session.commit()
            print(f"✅ Restored {count} records into '{name}'")


async def run_backup(send_telegram: bool = True, upload_github: bool = True, output_dest: Optional[str] = None) -> dict:
    """
    Unified backup execution function:
    1. Creates local compressed .sql.gz or .json.gz dump
    2. Uploads backup to GitHub Releases
    3. Uploads backup to Telegram Storage Channel
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backups_dir = Path("backups")
    backups_dir.mkdir(exist_ok=True)

    pg_url = get_pg_url()
    sql_backup_path = str(backups_dir / f"db_backup_{timestamp}.sql.gz")
    json_backup_path = str(backups_dir / f"db_backup_{timestamp}.json.gz")

    final_path = None
    if dump_via_pg_dump(sql_backup_path, pg_url):
        final_path = sql_backup_path
    else:
        print("Using Python fallback backup...")
        final_path = await dump_via_python_json(json_backup_path)

    file_size_mb = os.path.getsize(final_path) / (1024 * 1024)
    print(f"🎉 Backup created at: {final_path} ({file_size_mb:.2f} MB)")

    if output_dest:
        out_dest = Path(output_dest)
        if out_dest.is_dir():
            dest_file = out_dest / os.path.basename(final_path)
        else:
            dest_file = out_dest
        shutil.copy2(final_path, dest_file)
        print(f"Saved copy to: {dest_file}")

    github_url = None
    if upload_github:
        github_url = await upload_to_github_release(final_path, timestamp)

    if send_telegram:
        caption_lines = [
            f"📦 <b>PostgreSQL Database Backup</b>",
            f"🕒 <i>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</i>",
            f"📁 <code>{os.path.basename(final_path)}</code> ({file_size_mb:.2f} MB)"
        ]
        if github_url:
            caption_lines.append(f"\n🌐 <a href='{github_url}'><b>View on GitHub Releases</b></a>")

        caption = "\n".join(caption_lines)
        await send_to_telegram(final_path, caption)

    return {
        "file_path": final_path,
        "timestamp": timestamp,
        "size_mb": file_size_mb,
        "github_url": github_url
    }


async def main():
    parser = argparse.ArgumentParser(description="PostgreSQL Database Backup & Restore Tool")
    parser.add_argument("--output", "-o", help="Custom output path or directory for the backup file")
    parser.add_argument("--telegram", "-t", action="store_true", help="Send backup archive to Telegram Storage Channel")
    parser.add_argument("--github", "-g", action="store_true", help="Upload backup archive to GitHub Releases")
    parser.add_argument("--all", "-a", action="store_true", help="Save backup, send to Telegram, and upload to GitHub")
    parser.add_argument("--restore", "-r", help="Path to backup file (.sql, .sql.gz, or .json.gz) to restore")
    args = parser.parse_args()

    if args.restore:
        restore_file = args.restore
        if not os.path.exists(restore_file):
            print(f"❌ Restore file '{restore_file}' does not exist.")
            sys.exit(1)

        print(f"Restoring database from {restore_file}...")
        if restore_file.endswith(".json") or restore_file.endswith(".json.gz"):
            await restore_from_json(restore_file)
        else:
            pg_url = get_pg_url()
            cat_cmd = "zcat" if restore_file.endswith(".gz") else "cat"
            cmd = f"{cat_cmd} \"{restore_file}\" | psql \"{pg_url}\""
            res = subprocess.run(cmd, shell=True)
            if res.returncode == 0:
                print("✅ Database restore complete!")
            else:
                print("❌ Restoration failed.")
        return

    # Run backup with specified flags
    send_telegram = args.telegram or args.all
    upload_github = args.github or args.all

    await run_backup(
        send_telegram=send_telegram,
        upload_github=upload_github,
        output_dest=args.output
    )


if __name__ == "__main__":
    asyncio.run(main())
