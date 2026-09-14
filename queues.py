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


def cancel_all_active_tasks(format_filter: str = "all") -> int:
    """Cancels running active tasks matching format_filter, terminating subprocesses."""
    cancelled_count = 0
    norm_filter = format_filter.lower()

    for task_id, task in list(active_tasks.items()):
        fmt = str(task.get("format", "")).lower()
        should_cancel = (
            norm_filter == "all"
            or (norm_filter == "alac" and "alac" in fmt)
            or (norm_filter == "lossless" and "lossless" in fmt)
            or (norm_filter == "aac" and "aac" in fmt)
            or (norm_filter == "atmos" and "atmos" in fmt)
            or (norm_filter == "mv" and ("mv" in fmt or "video" in fmt))
        )
        if not should_cancel:
            continue

        task["cancelled"] = True
        proc = task.get("process")
        if proc:
            try:
                proc.kill()
            except Exception:
                pass

        # Notify Telegram status message if available
        status_msg = task.get("status_msg")
        if status_msg:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(
                        status_msg.edit_text("🚫 Download cancelled by administrator.")
                    )
            except Exception:
                pass

        cancelled_count += 1

    return cancelled_count


def clear_queue(queue_type: str = "all", cancel_active: bool = True) -> dict[str, int]:
    """Empties the requested queue(s), cancels active tasks if requested, and returns metrics."""
    removed = 0
    queues_to_clear = []

    if queue_type in ("all", "alac"):
        queues_to_clear.append((download_queue, user_in_queue, user_pending_jobs, user_locks))
    if queue_type in ("all", "lossless"):
        queues_to_clear.append((lossless_queue, lossless_in_queue, lossless_pending_jobs, lossless_locks))
    if queue_type in ("all", "aac"):
        queues_to_clear.append((aac_queue, aac_in_queue, aac_pending_jobs, aac_locks))
    if queue_type in ("all", "atmos"):
        queues_to_clear.append((atmos_queue, atmos_in_queue, atmos_pending_jobs, atmos_locks))
    if queue_type in ("all", "mv"):
        queues_to_clear.append((mv_queue, mv_in_queue, mv_pending_jobs, mv_locks))

    for q, in_q, pending, locks in queues_to_clear:
        while not q.empty():
            try:
                q.get_nowait()
                q.task_done()
                removed += 1
            except (asyncio.QueueEmpty, ValueError):
                break
        in_q.clear()
        pending.clear()
        locks.clear()

    cancelled_active = 0
    if cancel_active:
        cancelled_active = cancel_all_active_tasks(queue_type)

    return {
        "removed_jobs": removed,
        "cancelled_active": cancelled_active,
    }



