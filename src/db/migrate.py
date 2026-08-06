"""Migration runner: detect, auto-stamp, back up, upgrade.

Wraps Alembic so an operator never needs to know Alembic exists. The decision
tree it implements (docs/05 §7.1):

    alembic_version exists?  ── yes ──► upgrade to head
             │
             no
             │
    leads table exists?  ── yes ──► stamp 0001 (the tables predate migrations),
             │                      then upgrade to head
             no
             │
             └──► fresh database: upgrade from empty

The auto-stamp is what makes the live 459-row database safe: its eight tables
already exist, so applying 0001 would fail. Recording it as "already at 0001"
is correct, and every later revision then applies normally.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
BASELINE_REVISION = "0001_baseline"


@dataclass(frozen=True)
class MigrationStatus:
    current: str | None
    head: str
    is_current: bool
    backup_path: Path | None = None


class MigrationRunner:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    # ---------------------------------------------------------------- config

    def _config(self) -> Config:
        cfg = Config(str(ALEMBIC_INI))
        cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{self.db_path}")
        # env.py reads this so the two can never disagree.
        os.environ["ALEMBIC_DB_URL"] = f"sqlite:///{self.db_path}"
        return cfg

    def head_revision(self) -> str:
        script = ScriptDirectory.from_config(self._config())
        heads = script.get_heads()
        if len(heads) != 1:
            # A branched history breaks `upgrade head` in a way that is far
            # easier to diagnose here than three revisions later.
            raise RuntimeError(
                f"Expected exactly one Alembic head, found {len(heads)}: {heads}. "
                "The revision chain must stay linear."
            )
        return heads[0]

    def current_revision(self) -> str | None:
        if not self.db_path.exists():
            return None
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"
            ).fetchone()
            if not row:
                return None
        finally:
            conn.close()

        from sqlalchemy import create_engine

        engine = create_engine(f"sqlite:///{self.db_path}")
        try:
            with engine.connect() as connection:
                return MigrationContext.configure(connection).get_current_revision()
        finally:
            engine.dispose()

    def _has_legacy_tables(self) -> bool:
        """True when the eight pre-migration tables exist but Alembic does not."""
        if not self.db_path.exists():
            return False
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='leads'"
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    # ---------------------------------------------------------------- backup

    def backup(self) -> Path | None:
        """Back up via the SQLite backup API, not a file copy.

        A file copy is wrong under WAL: the ``-wal`` sibling holds committed
        pages that have not been checkpointed into the main file, so copying
        only ``leads.db`` can produce a database missing recent writes. The
        backup API accounts for that.
        """
        if not self.db_path.exists():
            return None

        backup_dir = self.db_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = backup_dir / f"{self.db_path.stem}-{stamp}.db"

        source = sqlite3.connect(self.db_path)
        dest = sqlite3.connect(target)
        try:
            source.backup(dest)
        finally:
            dest.close()
            source.close()

        log.info("database backed up to %s", target)
        return target

    # --------------------------------------------------------------- upgrade

    def status(self) -> MigrationStatus:
        head = self.head_revision()
        current = self.current_revision()
        return MigrationStatus(current=current, head=head, is_current=current == head)

    def ensure_current(self, *, backup: bool = True) -> MigrationStatus:
        """Bring the database to head, stamping and backing up as needed."""
        cfg = self._config()
        head = self.head_revision()
        current = self.current_revision()

        if current == head:
            return MigrationStatus(current=current, head=head, is_current=True)

        backup_path: Path | None = None
        if backup and self.db_path.exists():
            backup_path = self.backup()

        if current is None and self._has_legacy_tables():
            log.info(
                "existing tables found with no migration history — stamping %s", BASELINE_REVISION
            )
            command.stamp(cfg, BASELINE_REVISION)

        command.upgrade(cfg, "head")

        new_current = self.current_revision()
        return MigrationStatus(
            current=new_current,
            head=head,
            is_current=new_current == head,
            backup_path=backup_path,
        )

    def stamp(self, revision: str) -> None:
        command.stamp(self._config(), revision)

    def upgrade(self, revision: str = "head") -> None:
        command.upgrade(self._config(), revision)

    def downgrade(self, revision: str) -> None:
        command.downgrade(self._config(), revision)
