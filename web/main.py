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

from pathlib import Path
from aiohttp import web
import bot_control
import database
from admin_routes import admin_routes
from web import config
from web.routes import routes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("web.main")
logging.getLogger().addHandler(bot_control.dashboard_log_handler)


async def on_startup(app: web.Application):
    logger.info("Initializing database connection...")
    await database.init_db()
    logger.info(f"Local storage directory: {config.LOCAL_STORAGE_DIR}")


def create_app() -> web.Application:
    app = web.Application()
    app.add_routes(routes)
    app.add_routes(admin_routes)

    dashboard_dist = Path(__file__).resolve().parent.parent / "dashboard" / "dist"
    if dashboard_dist.exists():
        app.router.add_static("/dashboard/assets", dashboard_dist / "assets", name="dashboard_assets")

        async def serve_dashboard_root(request: web.Request):
            return web.FileResponse(dashboard_dist / "index.html")

        app.router.add_get("/dashboard", serve_dashboard_root)

        async def serve_dashboard_sub(request: web.Request):
            req_path = dashboard_dist / request.match_info.get("tail", "")
            if req_path.is_file():
                return web.FileResponse(req_path)
            return web.FileResponse(dashboard_dist / "index.html")

        app.router.add_get("/dashboard/{tail:.*}", serve_dashboard_sub)

    app.on_startup.append(on_startup)
    return app


def main():
    app = create_app()
    logger.info(f"🚀 Starting Standalone Apple Music Web Server on http://{config.SERVER_HOST}:{config.SERVER_PORT}...")
    web.run_app(app, host=config.SERVER_HOST, port=config.SERVER_PORT)


if __name__ == "__main__":
    main()
