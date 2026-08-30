import asyncio

download_queue: asyncio.Queue = asyncio.Queue()
user_in_queue: set[int] = set()
user_pending_jobs: dict[int, int] = {}

user_locks: dict[int, asyncio.Lock] = {}
active_tasks: dict[str, dict] = {}
pending_album_prompts: dict[str, dict] = {}

aac_queue: asyncio.Queue = asyncio.Queue()

aac_in_queue: set[int] = set()
aac_pending_jobs: dict[int, int] = {}
aac_locks: dict[int, asyncio.Lock] = {}

atmos_queue: asyncio.Queue = asyncio.Queue()

atmos_in_queue: set[int] = set()
atmos_pending_jobs: dict[int, int] = {}
atmos_locks: dict[int, asyncio.Lock] = {}

mv_queue: asyncio.Queue = asyncio.Queue()

mv_in_queue: set[int] = set()
mv_pending_jobs: dict[int, int] = {}
mv_locks: dict[int, asyncio.Lock] = {}

lossless_queue: asyncio.Queue = asyncio.Queue()

lossless_in_queue: set[int] = set()
lossless_pending_jobs: dict[int, int] = {}
lossless_locks: dict[int, asyncio.Lock] = {}


def is_user_busy(user_id: int) -> bool:
    """
    Checks if a user has an active download task in any queue (ALAC, Regular Lossless, AAC, Dolby Atmos, or Music Video).
    """
    return (
        user_id in user_in_queue
        or user_id in lossless_in_queue
        or user_id in aac_in_queue
        or user_id in atmos_in_queue
        or user_id in mv_in_queue
    )


def get_queue_stats() -> dict[str, int]:
    """Returns the current pending size of each queue."""
    return {
        "alac": download_queue.qsize(),
        "lossless": lossless_queue.qsize(),
        "aac": aac_queue.qsize(),
        "atmos": atmos_queue.qsize(),
        "mv": mv_queue.qsize(),
        "total": (
            download_queue.qsize()
            + lossless_queue.qsize()
            + aac_queue.qsize()
            + atmos_queue.qsize()
            + mv_queue.qsize()
        ),
    }


def clear_queue(queue_type: str = "all") -> int:
    """Empties the requested queue(s) and returns number of removed items."""
    removed = 0
    queues_to_clear = []

    if queue_type in ("all", "alac"):
        queues_to_clear.append((download_queue, user_in_queue, user_pending_jobs))
    if queue_type in ("all", "lossless"):
        queues_to_clear.append((lossless_queue, lossless_in_queue, lossless_pending_jobs))
    if queue_type in ("all", "aac"):
        queues_to_clear.append((aac_queue, aac_in_queue, aac_pending_jobs))
    if queue_type in ("all", "atmos"):
        queues_to_clear.append((atmos_queue, atmos_in_queue, atmos_pending_jobs))
    if queue_type in ("all", "mv"):
        queues_to_clear.append((mv_queue, mv_in_queue, mv_pending_jobs))

    for q, in_q, pending in queues_to_clear:
        while not q.empty():
            try:
                q.get_nowait()
                q.task_done()
                removed += 1
            except (asyncio.QueueEmpty, ValueError):
                break
        in_q.clear()
        pending.clear()

    return removed


