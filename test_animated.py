import os
import asyncio
import logging
import sys
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import database
from help import help_router

load_dotenv()

# Test Bot Token
TOKEN_API = os.getenv("TOKEN_API", "8149215255:AAEIitKPACkUheV_lZXWJT_56fafQqYPcAA")

dp = Dispatcher()


async def main() -> None:
    await database.init_db()

    bot = Bot(
        token=TOKEN_API,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    # Register only the help router for testing
    dp.include_router(help_router)

    print("🤖 Test Bot started using standard Long Polling!")
    print("Send /help <Apple Music URL> in Telegram to test animated motion covers.")
    
    # Clean up webhook if set previously so polling works smoothly
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


def setup_logging():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    if logger.hasHandlers():
        logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)


if __name__ == "__main__":
    setup_logging()
    asyncio.run(main())
