"""Engine, session and SQLite pragma configuration.

Two things changed here in Phase 1 and both matter:

1. **``create_all()`` is gone.** Schema is owned by Alembic. Leaving
   ``create_all()`` in place would mean that merely importing the app creates
   whatever tables happen to be in ``models.py`` — which would then collide with
   the migration that is supposed to create them ("table already exists"), with
   no clean way back. ``init_db()`` now runs migrations instead.

2. **Pragmas are applied on every connection.** SQLAlchemy pools connections, so
   a pragma set once on one connection does not apply to the next. The event
   listener is the only correct place for this.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

log = logging.getLogger(__name__)

DB_DIR = Path(__file__).parent.parent.parent / "data"
DB_PATH = DB_DIR / "leads.db"

ENGINE: Engine | None = None
SessionFactory: sessionmaker | None = None


def _configure_pragmas(dbapi_connection, connection_record) -> None:
    """Applied on *every* pooled connection. See docs/05 §8.

    ``foreign_keys`` is per-connection in SQLite and defaults to OFF, so without
    this listener every foreign key in the schema would be decorative.
    """
    cursor = dbapi_connection.cursor()
    try:
        # Concurrent reads alongside the single writer. Persistent once set.
        cursor.execute("PRAGMA journal_mode=WAL")
        # Wait rather than raising "database is locked" the instant a write
        # collides with the worker.
        cursor.execute("PRAGMA busy_timeout=10000")
        # Durable enough for WAL; the fsync-per-commit of FULL buys nothing here.
        cursor.execute("PRAGMA synchronous=NORMAL")
        # Off by default in SQLite. Must be set per connection.
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def init_db(db_path: str | Path | None = None, *, run_migrations: bool = True) -> Engine:
    """Create the engine and bring the schema up to date.

    Set ``run_migrations=False`` when the caller manages migrations itself (the
    ``migrate`` CLI command does, to avoid recursing).
    """
    global ENGINE, SessionFactory

    db_file = Path(db_path) if db_path else DB_PATH
    db_file.parent.mkdir(parents=True, exist_ok=True)

    ENGINE = create_engine(
        f"sqlite:///{db_file}",
        echo=False,
        future=True,
        # The worker thread and the Flask thread share this engine.
        connect_args={"check_same_thread": False},
    )
    event.listen(ENGINE, "connect", _configure_pragmas)

    if run_migrations:
        from .migrate import MigrationRunner

        MigrationRunner(db_file).ensure_current()

    SessionFactory = sessionmaker(
        bind=ENGINE,
        # Objects stay usable after commit. Without this, reading any attribute
        # of a committed object triggers a refresh query — and outside a session
        # scope, a DetachedInstanceError.
        expire_on_commit=False,
    )
    return ENGINE


def get_session() -> Session:
    """Return a new session, initialising the database on first use.

    Callers are responsible for closing it. Prefer :func:`session_scope`.
    """
    if SessionFactory is None:
        init_db()
    assert SessionFactory is not None
    return SessionFactory()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commits on success, rolls back on any exception."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
