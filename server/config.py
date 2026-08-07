import os
from dotenv import load_dotenv

load_dotenv()

TOKEN_API = os.getenv("TOKEN_API", "").strip().strip('"').strip("'")
API_ID = os.getenv("API_ID", "").strip().strip('"').strip("'")
API_HASH = os.getenv("API_HASH", "").strip().strip('"').strip("'")


STORAGE_CHANNEL_ID_STR = os.getenv("STORAGE_CHANNEL_ID", "").strip().strip('"').strip("'")
if not STORAGE_CHANNEL_ID_STR:
    STORAGE_CHANNEL_ID = -1004423011255
elif STORAGE_CHANNEL_ID_STR.startswith("@") or STORAGE_CHANNEL_ID_STR.startswith("http"):
    STORAGE_CHANNEL_ID = STORAGE_CHANNEL_ID_STR
else:
    try:
        STORAGE_CHANNEL_ID = int(STORAGE_CHANNEL_ID_STR)
    except ValueError:
        STORAGE_CHANNEL_ID = STORAGE_CHANNEL_ID_STR

DATABASE_URL = os.getenv("DATABASE_URL")
STREAM_SERVER_URL = os.getenv("STREAM_SERVER_URL", "https://stream.eepy.in")

SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8088"))

# Option to redirect stream calls directly to TG-FileStreamBot (/watch/{message_id})
USE_FILESTREAMBOT_REDIRECT = os.getenv("USE_FILESTREAMBOT_REDIRECT", "false").lower() == "true"
FILESTREAMBOT_BASE_URL = os.getenv("FILESTREAMBOT_BASE_URL", STREAM_SERVER_URL).rstrip("/")



