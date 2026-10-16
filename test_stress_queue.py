import asyncio
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock

import queues
from queues import (
    active_tasks,
    clear_queue,
    cancel_all_active_tasks,
    get_queue_stats,
    download_queue,
    aac_queue,
    atmos_queue,
    lossless_queue,
    user_in_queue,
    user_locks,
    user_pending_jobs,
)


async def run_stress_test():
    print("=" * 60)
    print("STARTING LOCAL QUEUE STRESS TEST")
    print("=" * 60)

    # 1. Test: Initial clean state
    clear_queue("all", cancel_active=True)
    initial_stats = get_queue_stats()
    assert initial_stats["total"] == 0, f"Expected total 0, got {initial_stats['total']}"
    print("[OK] Step 1: Initial state verified (0 items).")

    # 2. Test: Rapid enqueue of 120 items (simulating position 90+ freeze scenario)
    TOTAL_ITEMS = 120
    print(f"\n[Test] Enqueuing {TOTAL_ITEMS} items across all format queues...")

    for i in range(TOTAL_ITEMS):
        user_id = 1000 + (i % 10)  # 10 simulated concurrent users
        # Include headless tasks (msg=None) like the Admin Artist Cacher emits
        task = {
            "url": f"https://music.apple.com/us/album/test-track/{i}",
            "songs": None,
            "msg": None if i % 2 == 0 else MagicMock(message_id=i, chat=MagicMock(id=user_id)),
            "user_id": user_id,
            "status_msg": None,
            "download_mode": "tracks",
        }

        if i % 4 == 0:
            await download_queue.put(task)
        elif i % 4 == 1:
            await aac_queue.put(task)
        elif i % 4 == 2:
            await atmos_queue.put(task)
        else:
            await lossless_queue.put(task)

    stats = get_queue_stats()
    print(f"[OK] Step 2: Enqueued successfully. Current queue stats: {stats}")
    assert stats["total"] == TOTAL_ITEMS, f"Expected {TOTAL_ITEMS}, got {stats['total']}"

    # 3. Test: Mock active workers processing tasks with faults and headless tasks
    print("\n[Test] Simulating resilient worker processing with faults and headless items...")
    processed = 0
    errors_caught = 0

    async def mock_worker(queue_obj, name):
        nonlocal processed, errors_caught
        while not queue_obj.empty():
            try:
                task = await asyncio.wait_for(queue_obj.get(), timeout=0.1)
            except asyncio.TimeoutError:
                break

            # Verify safe handling of headless task
            uid = task.get("user_id", 999999999)
            msg = task.get("msg")
            task_id = f"{name}_{uid}_{int(time.time() * 1000)}"

            # Simulate simulated active task in queues.active_tasks
            proc_mock = MagicMock()
            proc_mock.kill = MagicMock()
            active_tasks[task_id] = {
                "process": proc_mock,
                "cancelled": False,
                "user_id": uid,
                "status_msg": None,
                "format": name.upper(),
                "status": "downloading",
                "start_time": time.time(),
                "progress": 50,
            }

            # Fault simulation: some tasks raise unexpected errors
            try:
                if uid % 3 == 0:
                    raise RuntimeError("Simulated network drop / gamdl error")
                await asyncio.sleep(0.001)
            except Exception:
                errors_caught += 1
            finally:
                active_tasks.pop(task_id, None)
                processed += 1
                queue_obj.task_done()

    # Process first 50 items
    worker_tasks = [
        asyncio.create_task(mock_worker(download_queue, "alac")),
        asyncio.create_task(mock_worker(aac_queue, "aac")),
        asyncio.create_task(mock_worker(atmos_queue, "atmos")),
        asyncio.create_task(mock_worker(lossless_queue, "lossless")),
    ]
    await asyncio.gather(*worker_tasks)
    print(f"[OK] Step 3: Worker processed tasks without dying! (Processed: {processed}, Faults handled safely: {errors_caught})")

    # 4. Test: Cancellation and Website "Clear Queue" while active
    remaining_before_clear = get_queue_stats()["total"]
    print(f"\n[Test] Testing website 'Clear Queue' with {remaining_before_clear} items remaining...")

    # Inject simulated running subprocesses to test active kill
    dummy_proc_1 = MagicMock()
    dummy_proc_1.kill = MagicMock()
    dummy_proc_2 = MagicMock()
    dummy_proc_2.kill = MagicMock()

    active_tasks["active_task_1"] = {
        "process": dummy_proc_1,
        "cancelled": False,
        "user_id": 99991,
        "status_msg": None,
    }
    active_tasks["active_task_2"] = {
        "process": dummy_proc_2,
        "cancelled": False,
        "user_id": 99992,
        "status_msg": None,
    }

    # User in-queue locks
    user_in_queue.add(99991)
    user_locks[99991] = asyncio.Lock()
    user_pending_jobs[99991] = 5

    # Run clear_queue with cancel_active=True
    removed = clear_queue("all", cancel_active=True)
    print(f"Purged {removed} pending tasks and cancelled active tasks.")

    dummy_proc_1.kill.assert_called_once()
    dummy_proc_2.kill.assert_called_once()
    print("[OK] Active subprocesses were killed.")

    assert 99991 not in user_in_queue, "User 99991 should have been removed from user_in_queue"
    assert 99991 not in user_locks, "User 99991 lock should have been released"
    print("[OK] User in-queue lock and pending jobs were cleanly released.")

    after_clear_stats = get_queue_stats()
    assert after_clear_stats["total"] == 0, f"Expected 0 after clear, got {after_clear_stats['total']}"
    assert len(active_tasks) == 0, f"Expected 0 active tasks after clear, got {len(active_tasks)}"
    print(f"[OK] Step 4: Full queue purge and active process kill verified (Remaining: {after_clear_stats['total']}).")

    # 5. Test: cancel_all_active_tasks helper
    active_tasks["stuck_task"] = {
        "process": dummy_proc_1,
        "cancelled": False,
        "user_id": 8888,
        "status_msg": None,
    }
    cancel_all_active_tasks()
    assert active_tasks["stuck_task"]["cancelled"] is True
    print("[OK] Step 5: cancel_all_active_tasks marks tasks cancelled properly.")
    active_tasks.clear()

    print("\n" + "=" * 60)
    print("ALL STRESS TESTS PASSED SUCCESSFULLY! QUEUE IS RESILIENT.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_stress_test())
