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
