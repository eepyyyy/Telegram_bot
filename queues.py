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


def cancel_all_active_tasks(format_filter: str = "all", remove: bool = False) -> int:
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

        async_task = task.get("async_task")
        if async_task and hasattr(async_task, "cancel") and not async_task.done():
            try:
                async_task.cancel()
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

        if remove:
            active_tasks.pop(task_id, None)

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
            except Exception:
                break
        in_q.clear()
        pending.clear()
        locks.clear()

    cancelled_active = 0
    if cancel_active:
        cancelled_active = cancel_all_active_tasks(queue_type, remove=True)

    return {
        "removed_jobs": removed,
        "cancelled_active": cancelled_active,
    }


def get_user_queue_status(user_id: int) -> dict[str, int]:
    """
    Returns the count of active downloads and pending queued items for user_id.
    """
    active_count = sum(1 for t in active_tasks.values() if t.get("user_id") == user_id and not t.get("cancelled"))

    queued_count = 0
    queues = [
        download_queue,
        lossless_queue,
        aac_queue,
        atmos_queue,
        mv_queue,
    ]
    for q in queues:
        try:
            for item in list(q._queue):
                item_user_id = None
                if isinstance(item, dict):
                    item_user_id = item.get("user_id")
                    if not item_user_id and "msg" in item:
                        m = item["msg"]
                        item_user_id = getattr(getattr(m, "from_user", None), "id", None) or getattr(m, "chat_id", None) or getattr(getattr(m, "chat", None), "id", None)
                elif isinstance(item, (list, tuple)) and len(item) > 0:
                    m = item[0]
                    item_user_id = getattr(getattr(m, "from_user", None), "id", None) or getattr(m, "chat_id", None) or getattr(getattr(m, "chat", None), "id", None)
                else:
                    item_user_id = getattr(item, "user_id", None)

                if item_user_id == user_id:
                    queued_count += 1
        except Exception:
            pass

    return {
        "active_count": active_count,
        "queued_count": queued_count,
    }


def cancel_user_active_downloads(user_id: int) -> int:
    """
    Cancels only the active running tasks for this user.
    Leaves pending queued items intact.
    """
    active_cancelled = 0
    for task_id, task in list(active_tasks.items()):
        if task.get("user_id") == user_id and not task.get("cancelled"):
            task["cancelled"] = True
            proc = task.get("process")
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass
            async_task = task.get("async_task")
            if async_task and hasattr(async_task, "cancel") and not async_task.done():
                try:
                    async_task.cancel()
                except Exception:
                    pass
            status_msg = task.get("status_msg")
            if status_msg:
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(
                            status_msg.edit_text("🚫 Active download cancelled by user.")
                        )
                except Exception:
                    pass
            active_cancelled += 1
    return active_cancelled


def clear_user_pending_queue(user_id: int) -> int:
    """
    Removes pending items from queues for this user.
    Leaves the currently running download intact.
    """
    queued_removed = 0
    queue_tuples = [
        (download_queue, user_in_queue, user_pending_jobs),
        (lossless_queue, lossless_in_queue, lossless_pending_jobs),
        (aac_queue, aac_in_queue, aac_pending_jobs),
        (atmos_queue, atmos_in_queue, atmos_pending_jobs),
        (mv_queue, mv_in_queue, mv_pending_jobs),
    ]

    for q, in_q, pending in queue_tuples:
        items = []
        while not q.empty():
            try:
                item = q.get_nowait()
                q.task_done()
                items.append(item)
            except Exception:
                break

        for item in items:
            item_user_id = None
            if isinstance(item, dict):
                item_user_id = item.get("user_id")
                if not item_user_id and "msg" in item:
                    m = item["msg"]
                    item_user_id = getattr(getattr(m, "from_user", None), "id", None) or getattr(m, "chat_id", None) or getattr(getattr(m, "chat", None), "id", None)
            elif isinstance(item, (list, tuple)) and len(item) > 0:
                m = item[0]
                item_user_id = getattr(getattr(m, "from_user", None), "id", None) or getattr(m, "chat_id", None) or getattr(getattr(m, "chat", None), "id", None)
            else:
                item_user_id = getattr(item, "user_id", None)

            if item_user_id == user_id:
                queued_removed += 1
                if isinstance(item, dict) and item.get("status_msg"):
                    try:
                        asyncio.create_task(item["status_msg"].edit_text("🚫 Queued download removed."))
                    except Exception:
                        pass
            else:
                q.put_nowait(item)

        in_q.discard(user_id)
        pending.pop(user_id, None)

    return queued_removed


def cancel_user_queue(user_id: int) -> dict[str, int]:
    """
    Cancels active tasks and removes pending queued tasks for a specific user_id.
    Returns {'active_cancelled': count, 'queued_removed': count}.
    """
    active_cancelled = cancel_user_active_downloads(user_id)
    queued_removed = clear_user_pending_queue(user_id)

    # Clean up locks if user has nothing left
    for locks in (user_locks, lossless_locks, aac_locks, atmos_locks, mv_locks):
        locks.pop(user_id, None)

    return {
        "active_cancelled": active_cancelled,
        "queued_removed": queued_removed,
    }




