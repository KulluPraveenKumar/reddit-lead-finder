"""``python main.py worker`` — the phase's standalone-worker acceptance criterion.

Driven through ``main()`` rather than by calling ``run_standalone`` directly,
because the criterion is about the *command*: a worker function that works while
the CLI that invokes it does not is a worker nobody can start.
"""

from __future__ import annotations

import threading

import pytest

import main as main_module
from src.orchestration.job_queue import JobQueue
from src.orchestration.worker import Worker, run_standalone


@pytest.fixture
def engine(temp_db):
    from src.db import database

    return database.ENGINE


def test_the_help_text_lists_the_worker_command(capsys):
    main_module.print_help()

    assert "python main.py worker" in capsys.readouterr().out


def test_main_dispatches_worker_to_cmd_worker(monkeypatch):
    called: list[object] = []
    monkeypatch.setattr(main_module.sys, "argv", ["main.py", "worker"])
    monkeypatch.setattr(main_module, "cmd_worker", lambda config: called.append(config))

    main_module.main()

    assert len(called) == 1


def test_cmd_worker_runs_a_queued_job_then_stops(engine, monkeypatch, capsys):
    """The full path: CLI → run_standalone → Worker → handler → done.

    Asserts the two lines the manual guide tells a tester to look for. A guide
    that quotes output nobody has ever captured is how a healthy repository gets
    recorded as a failure — the exact defect
    ``docs/FINAL_PRE_P2_REVIEW.md`` §7.1 found in the P00 and P01 guides.
    """
    queue = JobQueue(engine=engine)
    job = queue.enqueue("maintenance", payload={"vacuum": False})
    started = threading.Event()

    real_run_forever = Worker.run_forever

    def run_once(self):
        # Stop after the first pass so the foreground command terminates.
        started.set()
        self.tick()
        self.stop()
        real_run_forever(self)

    monkeypatch.setattr(Worker, "run_forever", run_once)
    monkeypatch.setattr(main_module, "init_db", lambda: None)

    main_module.cmd_worker({"worker": {"poll_interval_seconds": 0.01}})

    assert started.is_set()
    assert queue.get(job.id).state == "done"

    printed = capsys.readouterr().out
    assert "Worker started" in printed
    assert "Worker stopped." in printed


def test_run_standalone_installs_signal_handlers_and_exits_on_stop(engine, monkeypatch):
    installed: list[bool] = []
    monkeypatch.setattr(
        Worker, "install_signal_handlers", lambda self: installed.append(True) or self.stop()
    )

    run_standalone(poll_interval=0.01, queue=JobQueue(engine=engine), registry={})

    assert installed == [True]
