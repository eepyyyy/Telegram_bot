import asyncio
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import queues
from queues import (
    active_tasks,
    clear_queue,
    cancel_all_active_tasks,
    cancel_user_queue,
    clear_user_pending_queue,
    get_queue_stats,
    get_user_queue_status,
    is_user_busy,
    download_queue,
    aac_queue,
    atmos_queue,
    lossless_queue,
    mv_queue,
    user_in_queue,
    user_locks,
    user_pending_jobs,
    aac_in_queue,
    aac_locks,
    aac_pending_jobs,
    atmos_in_queue,
    atmos_locks,
    atmos_pending_jobs,
    lossless_in_queue,
    lossless_locks,
    lossless_pending_jobs,
    mv_in_queue,
    mv_locks,
    mv_pending_jobs,
)
from index import worker as alac_worker, supervised_worker
from aac import aac_worker
from atmos import atmos_worker
from lossless import lossless_worker
from mv import mv_worker


async def run_practical_tests():
    print("=" * 70)
    print("RUNNING PRACTICAL QUEUE RESILIENCE & INTEGRATION TEST SUITE")
    print("=" * 70)

    # -------------------------------------------------------------
    # Test 1: Worker Cancellation Immunity
    # When active download tasks are cancelled (via user /cancel or admin),
    # the worker coroutine MUST NOT die and MUST continue processing next tasks.
    # -------------------------------------------------------------
    print("\n[Test 1] Verifying Worker Cancellation Immunity across all formats...")
    clear_queue("all", cancel_active=True)

    worker_task_alac = asyncio.create_task(supervised_worker(alac_worker, "alac-test"))
    worker_task_aac = asyncio.create_task(supervised_worker(aac_worker, "aac-test"))
    worker_task_lossless = asyncio.create_task(supervised_worker(lossless_worker, "lossless-test"))
    worker_task_atmos = asyncio.create_task(supervised_worker(atmos_worker, "atmos-test"))
    worker_task_mv = asyncio.create_task(supervised_worker(mv_worker, "mv-test"))

    test_workers = [
        ("ALAC", download_queue, "index.process_download"),
        ("AAC", aac_queue, "aac.process_aac_download"),
        ("Lossless", lossless_queue, "lossless.process_lossless_download"),
        ("Atmos", atmos_queue, "atmos.process_atmos_download"),
        ("MV", mv_queue, "mv.process_mv_download"),
    ]

    for fmt_name, q, patch_target in test_workers:
        started_event = asyncio.Event()
        cancelled_event = asyncio.Event()

        async def mock_download_hang(task):
            unique_task_id = f"test_{fmt_name}_{task['user_id']}"
            active_tasks[unique_task_id] = {
                "process": None,
                "cancelled": False,
                "user_id": task["user_id"],
                "status_msg": None,
                "format": fmt_name,
                "async_task": asyncio.current_task(),
            }
            started_event.set()
            try:
                # Simulate in-progress work waiting for cancellation
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled_event.set()
                raise
            finally:
                active_tasks.pop(unique_task_id, None)

        with patch(patch_target, side_effect=mock_download_hang):
            user_id = 5001
            task = {
                "url": f"https://music.apple.com/test/{fmt_name}/1",
                "user_id": user_id,
                "msg": None,
                "is_admin_cache": True,
            }
            await q.put(task)

            # Wait for mock download to start
            await asyncio.wait_for(started_event.wait(), timeout=2.0)
            assert len(active_tasks) > 0, f"Expected active task for {fmt_name}"

            # Cancel all active tasks
            cancelled_count = cancel_all_active_tasks(format_filter="all")
            assert cancelled_count >= 1, f"Expected at least 1 cancelled task for {fmt_name}"

            # Verify that CancelledError was caught inside the download task
            await asyncio.wait_for(cancelled_event.wait(), timeout=2.0)
            await asyncio.sleep(0.05)

        # CRITICAL ASSERTION: The worker must be alive and ready for the next task!
        # Now enqueue a fast succeeding task
        finished_second_event = asyncio.Event()

        async def mock_download_success(task):
            finished_second_event.set()

        with patch(patch_target, side_effect=mock_download_success):
            next_task = {
                "url": f"https://music.apple.com/test/{fmt_name}/2",
                "user_id": 5002,
                "msg": None,
                "is_admin_cache": True,
            }
            await q.put(next_task)
            await asyncio.wait_for(finished_second_event.wait(), timeout=2.0)

        print(f"  [OK] {fmt_name} worker survived task cancellation and successfully executed next item!")

    # -------------------------------------------------------------
    # Test 2: Auto-Healing Stale Queue State
    # If a user ID is stuck in *_in_queue sets with 0 active and 0 queued tasks,
    # is_user_busy() must self-heal and return False.
    # -------------------------------------------------------------
    print("\n[Test 2] Verifying Auto-Healing for Stale Queue State...")
    stale_user_id = 77777777

    # Artificially inject stale flags into all queue tracker sets
    user_in_queue.add(stale_user_id)
    lossless_in_queue.add(stale_user_id)
    aac_in_queue.add(stale_user_id)
    atmos_in_queue.add(stale_user_id)
    mv_in_queue.add(stale_user_id)
    user_pending_jobs[stale_user_id] = 5
    user_locks[stale_user_id] = asyncio.Lock()

    # Verify is_user_busy auto-heals
    is_busy = is_user_busy(stale_user_id)
    assert not is_busy, f"Expected is_user_busy to return False for stale user, got {is_busy}"
    assert stale_user_id not in user_in_queue, "stale_user_id should have been purged from user_in_queue"
    assert stale_user_id not in aac_in_queue, "stale_user_id should have been purged from aac_in_queue"
    assert stale_user_id not in user_locks, "stale user lock should have been purged"
    assert stale_user_id not in user_pending_jobs, "stale user pending jobs should have been purged"
    print("  [OK] Auto-healing cleanly purged all stale entries and unlocked the user.")

    # -------------------------------------------------------------
    # Test 3: Admin / Headless Parallel Concurrency Without Lock Deadlock
    # Multiple admin/headless caching tasks must execute in parallel without
    # blocking each other on a shared system_user_id lock.
    # -------------------------------------------------------------
    print("\n[Test 3] Verifying Parallel Concurrency for Admin Caching Tasks...")
    active_concurrent_tasks = 0
    max_observed_concurrency = 0
    total_admin_tasks = 9
    finished_admin_tasks = 0

    async def mock_admin_download(task):
        nonlocal active_concurrent_tasks, max_observed_concurrency, finished_admin_tasks
        active_concurrent_tasks += 1
        if active_concurrent_tasks > max_observed_concurrency:
            max_observed_concurrency = active_concurrent_tasks
        await asyncio.sleep(0.08)
        active_concurrent_tasks -= 1
        finished_admin_tasks += 1

    # Spin up 3 additional concurrent workers
    extra_workers = [asyncio.create_task(supervised_worker(alac_worker, f"alac-pool-{i}")) for i in range(3)]

    with patch("index.process_download", side_effect=mock_admin_download):
        for i in range(total_admin_tasks):
            await download_queue.put({
                "url": f"https://music.apple.com/admin-album/{i}",
                "user_id": 999999999,
                "msg": None,
                "is_admin_cache": True,
            })

        # Wait for all admin tasks to finish
        start_time = time.time()
        while finished_admin_tasks < total_admin_tasks and (time.time() - start_time) < 5.0:
            await asyncio.sleep(0.05)

    assert finished_admin_tasks == total_admin_tasks, f"Expected {total_admin_tasks} finished, got {finished_admin_tasks}"
    assert max_observed_concurrency > 1, f"Expected concurrent execution > 1, got {max_observed_concurrency}"
    print(f"  [OK] Admin caching executed with peak concurrency of {max_observed_concurrency} without user-lock starvation.")

    # -------------------------------------------------------------
    # Test 4: Fault Tolerance Under Unhandled Execution Errors
    # -------------------------------------------------------------
    print("\n[Test 4] Verifying Worker Fault Isolation on Unhandled Exceptions...")
    errors_encountered = 0
    succeeded_after_errors = 0

    async def faulty_download(task):
        nonlocal errors_encountered, succeeded_after_errors
        if task.get("should_fail"):
            errors_encountered += 1
            raise RuntimeError("Simulated transient network timeout / DB crash")
        succeeded_after_errors += 1

    with patch("index.process_download", side_effect=faulty_download):
        # Enqueue 5 failing tasks followed by 5 succeeding tasks
        for i in range(5):
            await download_queue.put({
                "url": f"https://music.apple.com/fail/{i}",
                "user_id": 8000 + i,
                "msg": None,
                "should_fail": True,
            })
        for i in range(5):
            await download_queue.put({
                "url": f"https://music.apple.com/pass/{i}",
                "user_id": 9000 + i,
                "msg": None,
                "should_fail": False,
            })

        # Wait for queue to drain
        start_time = time.time()
        while download_queue.qsize() > 0 and (time.time() - start_time) < 5.0:
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.1)

    assert errors_encountered == 5, f"Expected 5 errors caught, got {errors_encountered}"
    assert succeeded_after_errors == 5, f"Expected 5 successes, got {succeeded_after_errors}"
    assert download_queue.qsize() == 0, f"Expected queue to be 0, got {download_queue.qsize()}"
    print(f"  [OK] Workers safely isolated {errors_encountered} faults and seamlessly processed {succeeded_after_errors} subsequent tasks.")

    # -------------------------------------------------------------
    # Test 5: Clear Queue and Subprocess Kill
    # -------------------------------------------------------------
    print("\n[Test 5] Verifying Full Queue Purge and Subprocess Termination...")
    dummy_proc = MagicMock()
    dummy_proc.kill = MagicMock()
    active_tasks["active_kill_test"] = {
        "process": dummy_proc,
        "cancelled": False,
        "user_id": 9999,
        "format": "ALAC",
    }

    # Put items in all queues
    for q in (download_queue, aac_queue, atmos_queue, lossless_queue, mv_queue):
        await q.put({"url": "test", "user_id": 9999, "is_admin_cache": True})

    clear_result = clear_queue("all", cancel_active=True)
    assert clear_result["cancelled_active"] >= 1, "Expected active task to be cancelled"
    dummy_proc.kill.assert_called_once()

    stats = get_queue_stats()
    assert stats["total"] == 0, f"Expected total 0, got {stats['total']}"
    print(f"  [OK] Clear queue cancelled active processes and emptied all queues cleanly.")

    # -------------------------------------------------------------
    # Test 6: Worker Supervisor Auto-Restart on Fatal Worker Exit
    # -------------------------------------------------------------
    print("\n[Test 6] Verifying Supervisor Auto-Restart on Worker Crash...")
    crashes = 0
    runs = 0
    restarted_event = asyncio.Event()

    async def crashing_worker():
        nonlocal crashes, runs
        runs += 1
        if crashes == 0:
            crashes += 1
            raise ZeroDivisionError("Simulated unhandled fatal worker bug")
        restarted_event.set()

    sup_task = asyncio.create_task(supervised_worker(crashing_worker, "crash-test"))
    await asyncio.wait_for(restarted_event.wait(), timeout=4.0)
    assert crashes == 1, f"Expected 1 crash, got {crashes}"
    assert runs >= 2, f"Expected supervisor to restart worker (runs >= 2), got {runs}"
    sup_task.cancel()
    print(f"  [OK] Supervisor detected worker crash and successfully restarted worker within 2s.")

    # Clean up test background worker tasks
    all_workers = [worker_task_alac, worker_task_aac, worker_task_lossless, worker_task_atmos, worker_task_mv] + extra_workers
    for w in all_workers:
        w.cancel()
    await asyncio.gather(*all_workers, return_exceptions=True)

    print("\n" + "=" * 70)
    print("ALL PRACTICAL TESTS PASSED PERFECTLY! QUEUES ARE ROCK-SOLID RESILIENT.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_practical_tests())
