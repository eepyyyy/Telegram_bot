import asyncio
import collections
import datetime
import logging
import os
import platform
import shutil
import time
from typing import Any, Optional

# Global Bot State
is_bot_paused: bool = False
maintenance_mode: bool = False
maintenance_message: str = "🚧 The bot is currently under maintenance. Please try again shortly."
bot_start_time: float = time.time()

# Concurrency overrides (if set via dashboard)
custom_worker_concurrency: dict[str, int] = {}

# In-memory log buffer (stores last 600 log lines)
LOG_BUFFER_MAX_SIZE = 600
log_buffer: collections.deque = collections.deque(maxlen=LOG_BUFFER_MAX_SIZE)


class DashboardLogHandler(logging.Handler):
    """Captures application logs in a fixed-size ring buffer for real-time dashboard viewing."""
    def emit(self, record: logging.LogRecord):
        try:
            entry = {
                "id": f"{record.created}_{record.msecs}",
                "timestamp": datetime.datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            log_buffer.append(entry)
        except Exception:
            self.handleError(record)


dashboard_log_handler = DashboardLogHandler()


def get_system_stats() -> dict[str, Any]:
    """Collects CPU, memory, and disk telemetry."""
    stats: dict[str, Any] = {
        "os": f"{platform.system()} {platform.release()}",
        "python_version": platform.python_version(),
        "uptime_seconds": int(time.time() - bot_start_time),
    }

    # Disk usage for current drive
    try:
        current_path = os.path.abspath(".")
        total, used, free = shutil.disk_usage(current_path)
        stats["disk"] = {
            "total_gb": round(total / (1024 ** 3), 2),
            "used_gb": round(used / (1024 ** 3), 2),
            "free_gb": round(free / (1024 ** 3), 2),
            "percent": round((used / total) * 100, 1) if total > 0 else 0,
        }
    except Exception as e:
        stats["disk"] = {"error": str(e), "percent": 0}

    # Optional psutil integration if available
    try:
        import psutil  # type: ignore
        stats["cpu_percent"] = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        stats["memory"] = {
            "total_gb": round(mem.total / (1024 ** 3), 2),
            "used_gb": round(mem.used / (1024 ** 3), 2),
            "percent": mem.percent,
        }
    except ImportError:
        stats["cpu_percent"] = 0
        stats["memory"] = {
            "total_gb": 0,
            "used_gb": 0,
            "percent": 0,
        }

    return stats


def set_pause_state(paused: bool) -> bool:
    global is_bot_paused
    is_bot_paused = paused
    logging.info(f"[Bot Control] Bot download queues {'PAUSED' if paused else 'RESUMED'}")
    return is_bot_paused


def set_maintenance_mode(enabled: bool, message: Optional[str] = None) -> tuple[bool, str]:
    global maintenance_mode, maintenance_message
    maintenance_mode = enabled
    if message:
        maintenance_message = message
    logging.info(f"[Bot Control] Maintenance mode set to {enabled}")
    return maintenance_mode, maintenance_message
