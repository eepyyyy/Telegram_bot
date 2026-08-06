import os
from dotenv import load_dotenv

load_dotenv()

TOKEN_API = os.getenv("TOKEN_API")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

STORAGE_CHANNEL_ID_STR = os.getenv("STORAGE_CHANNEL_ID", "-1004423011255")
try:
    STORAGE_CHANNEL_ID = int(STORAGE_CHANNEL_ID_STR)
except ValueError:
    STORAGE_CHANNEL_ID = -1004423011255

DATABASE_URL = os.getenv("DATABASE_URL")
STREAM_SERVER_URL = os.getenv("STREAM_SERVER_URL", "https://stream.eepy.in")

SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8088"))


