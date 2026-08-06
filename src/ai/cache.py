"""Response cache, content dedup, and the in-flight guard.

Three distinct mechanisms that are easy to conflate:

* **Response cache** — same prompt, same answer. Keyed on everything that could
  change the answer, so a prompt-version bump correctly misses.
* **Content dedup** — two *different* Reddit posts with byte-identical bodies
  resolve to one analysis. Keyed on content, not on prompt.
* **In-flight guard** — two threads asking the same question at the same moment
  make one request, not two. Without it, a concurrency pool of 8 processing a
  duplicated item issues 8 identical calls before any of them can populate the
  cache.

The cache is permanent by design: an unchanged prompt about unchanged text has
an unchanged answer. Deleting every row costs money to rebuild and changes no
result.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

_WHITESPACE = re.compile(r"\s+")
_MD_EMPHASIS = re.compile(r"[*_~`]+")
_EDIT_MARKER = re.compile(r"\n*\s*(edit|update)\s*\d*\s*:.*$", re.IGNORECASE | re.DOTALL)


def normalise_content(text: str) -> str:
    """Canonical form for content hashing.

    Collapses whitespace, casefolds, strips markdown emphasis and trailing edit
    markers — so "Edit: typo" appended to a post does not create a second
    analysis of the same discussion.
    """
    if not text:
        return ""
    out = _EDIT_MARKER.sub("", text)
    out = _MD_EMPHASIS.sub("", out)
    out = _WHITESPACE.sub(" ", out)
    return out.strip().casefold()


def content_hash(text: str) -> str:
    return hashlib.sha256(normalise_content(text).encode()).hexdigest()


def cache_key(
    *, provider: str, model: str, stage: str, prompt_version: int, system: str, user: str
) -> str:
    """Everything that could change the answer, and nothing that could not.

    ``model`` is included because the same prompt to a different model is a
    different question. ``prompt_version`` is included so a prompt edit
    correctly invalidates rather than silently serving stale judgements.
    """
    payload = "\x1f".join([provider, model, stage, str(prompt_version), system, user])
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class CacheEntry:
    key: str
    payload: Any
    stage: str
    prompt_version: int
    hits: int = 0


class _MISSING:
    """Sentinel: distinguishes "no result recorded" from "the result was None"."""


class InFlightGuard:
    """Collapses concurrent identical requests to one.

    Each key gets an Event. The first caller computes; the rest wait and reuse.
    Losers never issue a request at all.

    The waiter count is what makes this correct. Without it the leader's
    ``release()`` clears the published result while slower followers are still
    waiting, and they wake to find nothing — a race that only appears under real
    concurrency and is silent when it does.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, threading.Event] = {}
        self._results: dict[str, Any] = {}
        self._errors: dict[str, BaseException] = {}
        self._waiters: dict[str, int] = {}

    def acquire(self, key: str) -> tuple[bool, threading.Event]:
        """``(is_leader, event)``. The leader computes; followers wait."""
        with self._lock:
            event = self._events.get(key)
            if event is None:
                self._events[key] = threading.Event()
                self._waiters[key] = 0
                return True, self._events[key]
            self._waiters[key] = self._waiters.get(key, 0) + 1
            return False, event

    def publish(self, key: str, value: Any) -> None:
        with self._lock:
            self._results[key] = value
            event = self._events.get(key)
        if event:
            event.set()

    def fail(self, key: str, error: BaseException) -> None:
        with self._lock:
            self._errors[key] = error
            event = self._events.get(key)
        if event:
            event.set()

    def wait(self, key: str, event: threading.Event, timeout: float = 120.0) -> Any:
        """Block until the leader finishes. Returns ``_MISSING`` if it vanished."""
        try:
            if not event.wait(timeout):
                raise TimeoutError(f"Timed out waiting for in-flight request {key[:12]}")
            with self._lock:
                if key in self._errors:
                    raise self._errors[key]
                return self._results.get(key, _MISSING)
        finally:
            with self._lock:
                remaining = self._waiters.get(key, 1) - 1
                self._waiters[key] = max(0, remaining)
                if remaining <= 0 and key not in self._events:
                    # Leader already released; this was the last follower.
                    self._results.pop(key, None)
                    self._errors.pop(key, None)
                    self._waiters.pop(key, None)

    def release(self, key: str) -> None:
        """Called by the leader. Keeps the result alive while followers remain."""
        with self._lock:
            self._events.pop(key, None)
            if self._waiters.get(key, 0) <= 0:
                self._results.pop(key, None)
                self._errors.pop(key, None)
                self._waiters.pop(key, None)


class ResponseCache:
    """SQLite-backed, with an in-process layer in front.

    The memory layer is not an optimisation for its own sake: within one run the
    same prefix is asked about repeatedly, and a database round trip per lookup
    would show up in wall-clock time on a 200-item run.
    """

    def __init__(
        self, session_factory=None, *, memory_only: bool = False, max_memory_entries: int = 2000
    ):
        self._memory: dict[str, CacheEntry] = {}
        self._lock = threading.Lock()
        self._session_factory = session_factory
        self.memory_only = memory_only
        self.max_memory_entries = max_memory_entries
        self.guard = InFlightGuard()
        self.stats = {"hits": 0, "misses": 0, "memory_hits": 0, "db_hits": 0}

    # ------------------------------------------------------------------ read

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._memory.get(key)
            if entry is not None:
                entry.hits += 1
                self.stats["hits"] += 1
                self.stats["memory_hits"] += 1
                return entry.payload

        if not self.memory_only:
            payload = self._db_get(key)
            if payload is not None:
                self.stats["hits"] += 1
                self.stats["db_hits"] += 1
                return payload

        self.stats["misses"] += 1
        return None

    def _db_get(self, key: str) -> Any | None:
        session = self._open_session()
        if session is None:
            return None
        try:
            from ..db.models import AICache

            row = session.query(AICache).filter_by(cache_key=key).one_or_none()
            if row is None:
                return None
            row.hits = (row.hits or 0) + 1
            row.last_hit_at = datetime.now(UTC).replace(tzinfo=None)
            session.commit()
            return json.loads(row.payload_json)
        except Exception:
            log.debug("cache read failed", exc_info=True)
            return None
        finally:
            session.close()

    # ----------------------------------------------------------------- write

    def put(
        self,
        key: str,
        payload: Any,
        *,
        provider: str = "",
        model: str = "",
        stage: str = "",
        prompt_version: int = 1,
        item_content_hash: str | None = None,
    ) -> None:
        serialisable = payload.model_dump() if hasattr(payload, "model_dump") else payload

        with self._lock:
            if len(self._memory) >= self.max_memory_entries:
                # Crude but adequate: this is a within-run accelerator, and the
                # durable copy is in SQLite.
                self._memory.pop(next(iter(self._memory)))
            self._memory[key] = CacheEntry(
                key=key, payload=serialisable, stage=stage, prompt_version=prompt_version
            )

        if not self.memory_only:
            self._db_put(
                key,
                serialisable,
                provider=provider,
                model=model,
                stage=stage,
                prompt_version=prompt_version,
                item_content_hash=item_content_hash,
            )

    def _db_put(
        self, key, payload, *, provider, model, stage, prompt_version, item_content_hash
    ) -> None:
        session = self._open_session()
        if session is None:
            return
        try:
            from ..db.models import AICache

            existing = session.query(AICache).filter_by(cache_key=key).one_or_none()
            if existing is not None:
                return
            session.add(
                AICache(
                    cache_key=key,
                    provider=provider,
                    model=model,
                    stage=stage,
                    prompt_version=prompt_version,
                    content_hash=item_content_hash,
                    payload_json=json.dumps(payload, default=str),
                    hits=0,
                    created_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            session.commit()
        except Exception:
            log.debug("cache write failed", exc_info=True)
            session.rollback()
        finally:
            session.close()

    # --------------------------------------------------------- content dedup

    def get_by_content(self, item_content_hash: str, stage: str, prompt_version: int) -> Any | None:
        """The 'never analyse identical content twice' path."""
        if self.memory_only:
            return None
        session = self._open_session()
        if session is None:
            return None
        try:
            from ..db.models import AICache

            row = (
                session.query(AICache)
                .filter_by(
                    content_hash=item_content_hash, stage=stage, prompt_version=prompt_version
                )
                .first()
            )
            if row is None:
                return None
            self.stats["hits"] += 1
            self.stats["db_hits"] += 1
            return json.loads(row.payload_json)
        except Exception:
            log.debug("content-hash cache read failed", exc_info=True)
            return None
        finally:
            session.close()

    # --------------------------------------------------------------- support

    def _open_session(self):
        try:
            if self._session_factory is not None:
                return self._session_factory()
            from ..db.database import get_session

            return get_session()
        except Exception:
            return None

    @property
    def hit_ratio(self) -> float:
        total = self.stats["hits"] + self.stats["misses"]
        return self.stats["hits"] / total if total else 0.0

    def clear_memory(self) -> None:
        with self._lock:
            self._memory.clear()
