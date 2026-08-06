"""The worker loop: claim, heartbeat, execute, report.

The loop is small on purpose. Everything that can go wrong belongs to the queue
(claiming, retrying, reclaiming) or to a handler (the actual work); the worker
only sequences them and refuses to die. A worker that exits on a handler's
exception would turn one bad job into an outage.

Two guarantees P3 will depend on, both asserted in ``tests/test_worker.py``:

* **A handler's transaction is separate from the queue's.** The handler runs
  inside its own ``Session``; if it raises, its writes roll back and the queue
  still records the failure. Sharing one transaction would mean a rollback
  erased the evidence of why it rolled back.
* **SIGTERM finishes the job in flight.** ``stop()`` sets an event; the loop
  checks it between jobs, never inside one. Killing a job mid-write is what
  leases exist to clean up, not something to do deliberately.

Specification: ``docs/04-system-design.md`` §3, ``docs/13-phase-03.md`` §9.3.
"""

from __future__ import annotations

import logging
import os
import platform
import signal
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy.orm import Session

from src.db.models import Job
from src.obs.logging import log_context
from src.orchestration.handlers import REGISTRY, Handler
from src.orchestration.job_queue import JobQueue, RetryableError

log = logging.getLogger(__name__)

#: How long a claim is good for before the queue may reclaim it. Fifteen minutes
#: is longer than any current handler and short enough that a crashed worker's
#: work is picked up within one coffee break.
DEFAULT_LEASE_SECONDS = 900

#: Seconds between polls of an empty queue. Two is a compromise: the operator
#: notices nothing slower, and it costs ~43k trivial SELECTs a day.
DEFAULT_POLL_INTERVAL = 2.0

#: Grace period for the in-flight job when stopping. The phase's acceptance
#: criterion is "SIGTERM finishes the in-flight job and exits < 30 s".
SHUTDOWN_TIMEOUT_SECONDS = 30.0


def worker_inprocess_enabled() -> bool:
    """``WORKER_INPROCESS`` — the phase's rollback switch.

    Default true, per ``docs/34`` §P2 Config. Setting it false and not running
    ``main.py worker`` is the documented rollback: nothing claims, and since
    nothing enqueues yet either, the system behaves exactly as it did before P2.
    """
    return os.environ.get("WORKER_INPROCESS", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


class Worker:
    """Claims one job at a time and runs it. One thread, one job."""

    def __init__(
        self,
        queue: JobQueue | None = None,
        registry: dict[str, Handler] | None = None,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        worker_id: str | None = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> None:
        self.queue = queue or JobQueue()
        self.registry = REGISTRY if registry is None else registry
        self.poll_interval = poll_interval
        self.lease_seconds = lease_seconds
        # Host + pid + a short random tail: two workers on one machine must not
        # share an id, or `worker_id` stops identifying who holds the lease.
        self.worker_id = (
            worker_id or (f"{platform.node() or 'local'}-{os.getpid()}-{uuid.uuid4().hex[:6]}")[:80]
        )
        self._stop = threading.Event()

    # -- lifecycle ----------------------------------------------------------

    def run_forever(self) -> None:
        """Claim and execute until :meth:`stop` is called."""
        log.info("worker started", extra={"worker_id": self.worker_id})
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                # The loop outlives every failure inside it. Anything reaching
                # here is a bug in the queue itself, and sleeping before the
                # retry stops it becoming a hot loop against the database.
                log.exception("worker tick failed")
                self._stop.wait(self.poll_interval)
        log.info("worker stopped", extra={"worker_id": self.worker_id})

    def tick(self) -> bool:
        """One iteration. Returns whether a job was executed.

        Split out of :meth:`run_forever` so tests can drive the worker one step
        at a time instead of racing a thread.
        """
        self.queue.reclaim_expired()
        job = self.queue.claim(self.worker_id, lease_seconds=self.lease_seconds)
        if job is None:
            self._stop.wait(self.poll_interval)
            return False
        self.execute(job)
        return True

    def stop(self) -> None:
        """Ask the loop to finish the current job and exit."""
        self._stop.set()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def install_signal_handlers(self) -> None:
        """SIGTERM/SIGINT → graceful stop. Main thread only.

        Guarded rather than assumed: ``signal.signal`` raises off the main
        thread, and the in-process worker runs in a daemon thread where the host
        process owns the signals.
        """
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self._on_signal)
            except (ValueError, OSError, AttributeError):
                log.debug("signal %s not installable here", sig)

    def _on_signal(self, signum: int, _frame: Any) -> None:
        log.info("signal %s received, finishing the job in flight", signum)
        self.stop()

    # -- execution ----------------------------------------------------------

    def execute(self, job: Job) -> None:
        """Run one job's handler and report the outcome to the queue."""
        handler = self.registry.get(job.job_type)
        if handler is None:
            # Not retryable: an unregistered type will still be unregistered in
            # ten minutes, and burning five attempts on it hides the typo.
            self.queue.fail(job.id, f"no handler registered for {job.job_type!r}", retryable=False)
            return

        with log_context(run_id=job.run_id, job_id=job.id, stage=job.job_type):
            try:
                with self._heartbeat(job.id), self._handler_session() as session:
                    result = handler(session, job)
            except RetryableError as exc:
                self.queue.fail(job.id, str(exc), retryable=True)
            except Exception as exc:
                log.exception("handler raised")
                self.queue.fail(job.id, repr(exc), retryable=False)
            else:
                self.queue.complete(job.id, result if isinstance(result, dict) else None)

    @contextmanager
    def _handler_session(self) -> Iterator[Session]:
        """The handler's own transaction: commits on success, rolls back on error."""
        session = Session(bind=self.queue.engine, expire_on_commit=False)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @contextmanager
    def _heartbeat(self, job_id: int) -> Iterator[None]:
        """Extend the lease every ``lease/3`` for as long as the handler runs.

        A third of the lease, not a half: one missed heartbeat must not be enough
        to lose the job.
        """
        interval = max(1.0, self.lease_seconds / 3)
        done = threading.Event()

        def beat() -> None:
            while not done.wait(interval):
                try:
                    self.queue.heartbeat(job_id, extend_seconds=self.lease_seconds)
                except Exception:
                    log.warning("heartbeat failed", extra={"job_id": job_id})

        thread = threading.Thread(target=beat, name=f"heartbeat-{job_id}", daemon=True)
        thread.start()
        try:
            yield
        finally:
            done.set()
            thread.join(timeout=5.0)


def start_inprocess_worker(
    queue: JobQueue | None = None,
    registry: dict[str, Handler] | None = None,
) -> Worker | None:
    """Start a worker on a daemon thread, or return ``None`` if disabled.

    P2 ships the helper and the standalone ``main.py worker`` command; wiring it
    into ``create_app()`` belongs to P3, which owns ``src/dashboard/app.py``.
    """
    if not worker_inprocess_enabled():
        log.info("in-process worker disabled by WORKER_INPROCESS")
        return None

    worker = Worker(queue, registry)
    thread = threading.Thread(target=worker.run_forever, name="worker", daemon=True)
    thread.start()
    return worker


def run_standalone(
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    *,
    queue: JobQueue | None = None,
    registry: dict[str, Handler] | None = None,
) -> None:
    """Blocking worker for ``python main.py worker``.

    Ignores ``WORKER_INPROCESS``: that flag governs whether the *dashboard*
    starts a worker of its own. Running this command is an explicit instruction.
    """
    worker = Worker(queue, registry, poll_interval=poll_interval)
    worker.install_signal_handlers()
    worker.run_forever()
