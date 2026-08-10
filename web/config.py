import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Base project directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Web server settings
SERVER_HOST = os.getenv("WEB_SERVER_HOST", os.getenv("SERVER_HOST", "0.0.0.0")).strip().strip('"').strip("'")
SERVER_PORT = int(os.getenv("WEB_SERVER_PORT", os.getenv("SERVER_PORT", "8034")))

# Dynamic local media storage path (defaults to ./downloads for VPS relative portability)
RAW_STORAGE_DIR = os.getenv("LOCAL_STORAGE_DIR", "./downloads").strip()
if os.path.isabs(RAW_STORAGE_DIR):
    LOCAL_STORAGE_DIR = Path(RAW_STORAGE_DIR)
else:
    LOCAL_STORAGE_DIR = (BASE_DIR / RAW_STORAGE_DIR).resolve()

# Base streaming URL (optional public domain)
STREAM_SERVER_URL = os.getenv("STREAM_SERVER_URL", "https://strem.eepy.in").rstrip("/")

# Ensure storage directories exist
def init_storage_dirs():
    for sub in ["alac", "aac", "atmos", "mv", "temp"]:
        target = LOCAL_STORAGE_DIR / sub
        target.mkdir(parents=True, exist_ok=True)

init_storage_dirs()
