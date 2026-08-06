import asyncio

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import logging
from aiohttp import web
import database
from server import config
from server.client import start_client, stop_client
from server.routes import routes


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("server.main")


async def on_startup(app: web.Application):
    logger.info("Initializing database...")
    await database.init_db()
    logger.info("Starting Pyrogram MTProto client...")
    try:
        await start_client()
    except Exception as e:
        logger.error(f"Could not start Pyrogram MTProto client: {e}. Check API_ID and API_HASH in .env.")


async def on_cleanup(app: web.Application):
    logger.info("Stopping Pyrogram MTProto client...")
    await stop_client()


def create_app() -> web.Application:
    app = web.Application()
    app.add_routes(routes)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def main():
    app = create_app()
    logger.info(f"Starting Telegram Cloud Stream Server on {config.SERVER_HOST}:{config.SERVER_PORT}...")
    web.run_app(app, host=config.SERVER_HOST, port=config.SERVER_PORT)


if __name__ == "__main__":
    main()
