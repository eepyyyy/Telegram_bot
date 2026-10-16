"""
Standalone utility script to calculate and backfill file sizes for all previous ZIP files in the database.
Queries Telegram Bot API using each cached ZIP document's file_id and updates the database records.

Usage:
    uv run python backfill_zip_sizes.py
"""
import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv()


async def main():
    print("=" * 60)
    print("📦 Telegram Bot - Previous ZIP File Sizes Calculator & Backfill")
    print("=" * 60)

    import database
    print("🔧 Ensuring database schema and columns are up to date...")
    await database.init_db()

    import crud
    print("🚀 Querying database for albums with cached ZIPs...")
    stats = await crud.backfill_missing_zip_sizes()

    print("\n" + "=" * 60)
    print("📊 Backfill Summary:")
    print(f"  • Total Albums Checked: {stats.get('total_found', 0)}")
    print(f"  • Successfully Updated: {stats.get('updated', 0)}")
    print(f"  • Failed / Inaccessible: {stats.get('failed', 0)}")
    print(f"  • Skipped (Already Sized): {stats.get('skipped', 0)}")
    print("=" * 60)
    print("✅ Finished!")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    asyncio.run(main())
