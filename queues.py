import asyncio

download_queue: asyncio.Queue = asyncio.Queue()
user_in_queue: set[int] = set()

user_locks: dict[int, asyncio.Lock] = {}