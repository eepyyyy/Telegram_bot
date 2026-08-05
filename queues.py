import asyncio

download_queue: asyncio.Queue = asyncio.Queue()
user_in_queue: set[int] = set()
user_pending_jobs: dict[int, int] = {}

user_locks: dict[int, asyncio.Lock] = {}
active_tasks: dict[str, dict] = {}

aac_queue: asyncio.Queue = asyncio.Queue()

aac_in_queue: set[int] = set()
aac_pending_jobs: dict[int, int] = {}
aac_locks: dict[int, asyncio.Lock] = {}

atmos_queue: asyncio.Queue = asyncio.Queue()

atmos_in_queue: set[int] = set()
atmos_pending_jobs: dict[int, int] = {}
atmos_locks: dict[int, asyncio.Lock] = {}


def is_user_busy(user_id: int) -> bool:
    """
    Checks if a user has an active download task in any queue (ALAC, AAC, or Dolby Atmos).
    """
    return user_id in user_in_queue or user_id in aac_in_queue or user_id in atmos_in_queue
