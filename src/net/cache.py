"""HTTP response cache.

Short-TTL and content-addressed. Its job is to stop a re-run within one session
re-fetching pages that have not changed — every avoided request is one fewer
chance to be rate limited, which matters more here than the latency saving.

**Blocks are never cached.** A cached block outlives its cause and turns a
transient rate limit into a persistent empty result.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from datetime import UTC, datetime, timedelta

log = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 900


def cache_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


class HTTPCache:
    def __init__(
        self,
        *,
        ttl: int = DEFAULT_TTL_SECONDS,
        memory_only: bool = False,
        max_memory_entries: int = 500,
    ):
        self.ttl = ttl
        self.memory_only = memory_only
        self.max_memory_entries = max_memory_entries
        self._memory: dict[str, tuple[str, datetime]] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, url: str) -> str | None:
        key = cache_key(url)
        now = datetime.now(UTC).replace(tzinfo=None)

        with self._lock:
            entry = self._memory.get(key)
            if entry is not None:
                body, expires = entry
                if expires > now:
                    self.hits += 1
                    return body
                del self._memory[key]

        if not self.memory_only:
            body = self._db_get(key, now)
            if body is not None:
                self.hits += 1
                return body

        self.misses += 1
        return None

    def put(self, url: str, body: str, *, ttl: int | None = None) -> None:
        key = cache_key(url)
        expires = datetime.now(UTC).replace(tzinfo=None) + timedelta(
            seconds=ttl if ttl is not None else self.ttl
        )
        with self._lock:
            if len(self._memory) >= self.max_memory_entries:
                self._memory.pop(next(iter(self._memory)))
            self._memory[key] = (body, expires)
        if not self.memory_only:
            self._db_put(key, url, body, expires)

    def _db_get(self, key: str, now: datetime) -> str | None:
        try:
            from ..db.database import get_session
            from ..db.models import HttpCache

            session = get_session()
            try:
                row = session.query(HttpCache).filter_by(cache_key=key).one_or_none()
                if row is None:
                    return None
                if row.expires_at and row.expires_at <= now:
                    session.delete(row)
                    session.commit()
                    return None
                row.hits = (row.hits or 0) + 1
                session.commit()
                return row.body
            finally:
                session.close()
        except Exception:
            log.debug("http cache read failed", exc_info=True)
            return None

    def _db_put(self, key: str, url: str, body: str, expires: datetime) -> None:
        try:
            from ..db.database import session_scope
            from ..db.models import HttpCache

            with session_scope() as session:
                row = session.query(HttpCache).filter_by(cache_key=key).one_or_none()
                now = datetime.now(UTC).replace(tzinfo=None)
                if row is None:
                    session.add(
                        HttpCache(
                            cache_key=key,
                            url=url[:2000],
                            body=body,
                            fetched_at=now,
                            expires_at=expires,
                            hits=0,
                        )
                    )
                else:
                    row.body, row.fetched_at, row.expires_at = body, now, expires
        except Exception:
            log.debug("http cache write failed", exc_info=True)

    def purge_expired(self) -> int:
        try:
            from ..db.database import session_scope
            from ..db.models import HttpCache

            now = datetime.now(UTC).replace(tzinfo=None)
            with session_scope() as session:
                return session.query(HttpCache).filter(HttpCache.expires_at <= now).delete()
        except Exception:
            return 0

    def clear_memory(self) -> None:
        with self._lock:
            self._memory.clear()

    @property
    def hit_ratio(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0
