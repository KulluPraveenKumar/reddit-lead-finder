"""K13 — SQLite writer contention under a worker and a reader at the same time.

The phase's acceptance criterion is a **10-minute** concurrent read/write soak
with zero ``database is locked``. Ten minutes cannot live in a 60-second suite,
so the duration is a parameter:

* by default the test runs ``SOAK_DEFAULT_SECONDS`` (20 s) — long enough to
  catch a missing ``busy_timeout`` or a long-held write lock, short enough for
  CI;
* ``SOAK_SECONDS=600 pytest tests/test_concurrency_soak.py`` runs the real thing.

The full 600-second run is executed by hand once per phase and its measured
output is recorded in the completion report. A criterion met by a shortened
proxy, with the real run recorded, is honest; shipping the 20-second version as
"the soak" would not be.
"""

from __future__ import annotations

import os
import threading
import time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from src.db.models import Job, Run, RunEvent
from src.obs.events import emit_event
from src.orchestration.job_queue import JobQueue

#: Long enough to exercise contention, short enough to keep the suite fast.
SOAK_DEFAULT_SECONDS = 20.0

#: What the phase actually claims. Run it with SOAK_SECONDS=600.
SOAK_FULL_SECONDS = 600.0


def soak_seconds() -> float:
    return float(os.environ.get("SOAK_SECONDS", SOAK_DEFAULT_SECONDS))


@pytest.fixture
def engine(temp_db):
    from src.db import database

    return database.ENGINE


def test_concurrent_read_write_soak_reports_no_locked_database(engine):
    """Worker writes, dashboard reads, both continuously. Zero lock errors."""
    duration = soak_seconds()
    queue = JobQueue(engine=engine)

    with Session(bind=engine) as session:
        run = Run(state="scraping")
        session.add(run)
        session.commit()
        run_id = run.id

    errors: list[str] = []
    counters = {"claims": 0, "reads": 0, "events": 0}
    stop = threading.Event()
    lock = threading.Lock()

    def record(exc: Exception) -> None:
        with lock:
            errors.append(f"{type(exc).__name__}: {exc}")

    def writer() -> None:
        """The worker's shape: enqueue, claim, emit an event, complete."""
        while not stop.is_set():
            try:
                job = queue.enqueue("maintenance", run_id=run_id)
                claimed = queue.claim("soak-writer", lease_seconds=60)
                if claimed is not None:
                    with Session(bind=engine) as session:
                        emit_event(session, run_id, "soak.tick", job_id=claimed.id)
                        session.commit()
                    queue.complete(claimed.id, {"ok": True})
                    with lock:
                        counters["claims"] += 1
                        counters["events"] += 1
                else:
                    queue.cancel_queued(job.run_id or run_id)
            except Exception as exc:  # noqa: BLE001 - the point is to record it
                record(exc)

    def reader() -> None:
        """The dashboard's shape: the progress GROUP BY, polled continuously."""
        while not stop.is_set():
            try:
                with Session(bind=engine) as session:
                    session.execute(text("SELECT state, COUNT(*) FROM jobs GROUP BY state")).all()
                    session.query(RunEvent).filter(RunEvent.run_id == run_id).count()
                    session.query(Job).count()
                with lock:
                    counters["reads"] += 1
            except Exception as exc:  # noqa: BLE001
                record(exc)

    # Two writers, not one: a single writer never contends with itself, and a
    # soak that cannot produce contention cannot prove its absence. Mutation
    # testing found this — with one writer, setting `busy_timeout=0` left this
    # test green.
    threads = [
        threading.Thread(target=writer, name="soak-writer-1"),
        threading.Thread(target=writer, name="soak-writer-2"),
        threading.Thread(target=reader, name="soak-reader-1"),
        threading.Thread(target=reader, name="soak-reader-2"),
    ]
    for thread in threads:
        thread.start()

    time.sleep(duration)
    stop.set()
    for thread in threads:
        thread.join(timeout=60)

    # Printed so the completion report can quote measured throughput rather than
    # "it passed". Visible with `pytest -s`.
    print(
        f"\nsoak {duration:.0f}s: {counters['claims']} claims, "
        f"{counters['events']} events, {counters['reads']} reads, {len(errors)} errors"
    )

    locked = [e for e in errors if "database is locked" in e or "database table is locked" in e]
    assert locked == [], f"{len(locked)} lock errors in {duration:.0f}s: {locked[:3]}"
    assert errors == [], f"unexpected errors during the soak: {errors[:3]}"
    assert counters["claims"] > 0, "the writer never claimed anything"
    assert counters["reads"] > 0, "the reader never ran"


def test_the_pragmas_that_make_the_soak_possible_are_actually_set(engine):
    """WAL and a busy timeout are the mitigation. Assert them, do not assume."""
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() >= 5000
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_a_write_lock_held_elsewhere_is_waited_for_not_failed_on(engine):
    """``busy_timeout`` in action: the second writer waits rather than raising."""
    queue = JobQueue(engine=engine)
    queue.enqueue("maintenance")
    released = threading.Event()
    result: list[object] = []

    def hold_the_write_lock() -> None:
        raw = engine.raw_connection()
        try:
            cursor = raw.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute("UPDATE jobs SET priority = priority")
            time.sleep(0.5)
            raw.commit()
            cursor.close()
        finally:
            raw.close()
            released.set()

    holder = threading.Thread(target=hold_the_write_lock)
    holder.start()
    time.sleep(0.1)
    try:
        result.append(queue.claim("waiter", lease_seconds=60))
    except OperationalError as exc:  # pragma: no cover - the failure we guard against
        pytest.fail(f"claim raised instead of waiting: {exc}")
    finally:
        holder.join(timeout=30)

    assert released.is_set()
    assert result[0] is not None, "the claim gave up instead of waiting for the lock"
