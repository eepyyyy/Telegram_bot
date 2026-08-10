import asyncio
import logging
import sys

# UTF-8 stdout fix for Windows
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from aiohttp import web
import database
from web import config
from web.routes import routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("web.main")


async def on_startup(app: web.Application):
    logger.info("Initializing database connection...")
    await database.init_db()
    logger.info(f"Local storage directory: {config.LOCAL_STORAGE_DIR}")


def create_app() -> web.Application:
    app = web.Application()
    app.add_routes(routes)
    app.on_startup.append(on_startup)
    return app


def main():
    app = create_app()
    logger.info(f"🚀 Starting Standalone Apple Music Web Server on http://{config.SERVER_HOST}:{config.SERVER_PORT}...")
    web.run_app(app, host=config.SERVER_HOST, port=config.SERVER_PORT)


if __name__ == "__main__":
    main()
