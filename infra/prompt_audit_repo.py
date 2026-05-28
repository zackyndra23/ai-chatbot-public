"""Prompt-audit writer backends.

Pluggable storage for LLM-call audit rows. Selected by env via build_writer().
The writer is invoked from a background ThreadPoolExecutor — it must never
block the user-facing turn and must never raise into the caller.

Backends:
    NoopPromptAuditWriter    — silent drop, used when PROMPT_AUDIT_BACKEND=noop
    MongoPromptAuditWriter   — persistent MongoClient + bounded queue + atexit flush
    (postgres reserved; not implemented in this iteration)
"""
from __future__ import annotations

import atexit
import os
import queue
import threading
from abc import ABC, abstractmethod
from typing import Callable, Optional


class PromptAuditWriter(ABC):
    @abstractmethod
    def write(self, doc: dict) -> None: ...

    @abstractmethod
    def close(self) -> None: ...


class NoopPromptAuditWriter(PromptAuditWriter):
    """Silent drop. Used when PROMPT_AUDIT_BACKEND=noop."""

    def write(self, doc: dict) -> None:
        return None

    def close(self) -> None:
        return None


class MongoPromptAuditWriter(PromptAuditWriter):
    """Persistent MongoClient + bounded queue + ThreadPoolExecutor.

    write() is non-blocking: enqueues onto a fixed-size queue. On full queue,
    the doc is dropped and `dropped` counter increments. A worker thread
    drains the queue and inserts. Failures inside the worker are swallowed.
    """

    _SHUTDOWN_SENTINEL = object()

    def __init__(
        self,
        *,
        client_factory: Optional[Callable[[], object]] = None,
        db_name: Optional[str] = None,
        coll_name: Optional[str] = None,
        queue_size: int = 1024,
        workers: int = 1,
    ):
        self._client_factory = client_factory or self._default_client_factory
        self._db_name = db_name
        self._coll_name = coll_name
        self._client = None
        self._coll = None
        self._indexes_ensured = False
        self._lock = threading.Lock()

        self._queue: "queue.Queue[object]" = queue.Queue(maxsize=max(1, int(queue_size)))
        self._closing = False
        self.dropped = 0
        self.failed = 0

        # Use plain `threading.Thread(daemon=True)` workers instead of
        # `ThreadPoolExecutor` so that the host process (Flask chatbot,
        # uvicorn, CLI smoke) can exit cleanly on Ctrl+C without waiting
        # for in-flight Mongo inserts. Audit is best-effort by spec — losing
        # at-most-N in-flight writes on shutdown is acceptable.
        self._workers: list[threading.Thread] = []
        n = max(1, int(workers))
        for i in range(n):
            t = threading.Thread(
                target=self._worker,
                name=f"prompt-audit-{i}",
                daemon=True,
            )
            t.start()
            self._workers.append(t)

    @staticmethod
    def _default_client_factory():
        from pymongo import MongoClient
        from core.app_config import Config
        cfg = Config()
        return MongoClient(cfg.MONGO_URI, connect=False)

    def _coll_lazy(self):
        if self._coll is not None:
            return self._coll
        with self._lock:
            if self._coll is not None:
                return self._coll
            from core.app_config import Config
            cfg = Config()
            self._client = self._client_factory()
            db = self._client[self._db_name or cfg.MONGO_DB]
            self._coll = db[self._coll_name or cfg.QUERY_RECORDING_COLL]
            self._ensure_indexes()
        return self._coll

    def _ensure_indexes(self):
        if self._indexes_ensured:
            return
        try:
            self._coll.create_index([("sessionId", 1), ("timestamp", -1)], name="idx_session_ts")
            self._coll.create_index([("timestamp", -1)], name="idx_ts")
            self._coll.create_index([("route", 1), ("stage", 1), ("timestamp", -1)], name="idx_route_stage_ts")
        except Exception:
            pass
        self._indexes_ensured = True

    def _worker(self):
        while True:
            item = self._queue.get()
            try:
                if item is self._SHUTDOWN_SENTINEL:
                    return
                try:
                    coll = self._coll_lazy()
                    coll.insert_one(item)
                except Exception:
                    self.failed += 1
            finally:
                self._queue.task_done()

    def _sync_write_for_test(self, doc: dict) -> None:
        coll = self._coll_lazy()
        coll.insert_one(doc)

    def write(self, doc: dict) -> None:
        if self._closing:
            self.dropped += 1
            return
        try:
            self._queue.put_nowait(doc)
        except queue.Full:
            self.dropped += 1

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        # Send one sentinel per worker. Short timeout — workers are daemon,
        # so even if sentinels don't land, process exit reaps them.
        for _ in self._workers:
            try:
                self._queue.put(self._SHUTDOWN_SENTINEL, timeout=2)
            except Exception:
                pass
        # Brief join — give workers a chance to drain naturally. Don't block
        # forever; Ctrl+C / process exit must remain responsive.
        for t in self._workers:
            try:
                t.join(timeout=2)
            except Exception:
                pass
        c = self._client
        if c is not None:
            try:
                c.close()
            except Exception:
                pass
        self._client = None
        self._coll = None


def build_writer(*, client_factory: Optional[Callable[[], object]] = None) -> PromptAuditWriter:
    """Construct the writer based on PROMPT_AUDIT_BACKEND env / config.

    `client_factory` is for tests. Production calls with no kwargs.
    Reads env directly so test env-var overrides take effect without
    re-importing Config.
    """
    from core.app_config import Config
    cfg = Config()
    backend = (os.getenv("PROMPT_AUDIT_BACKEND") or cfg.PROMPT_AUDIT_BACKEND or "mongo").strip().lower()

    if backend == "noop":
        w: PromptAuditWriter = NoopPromptAuditWriter()
    elif backend == "mongo":
        w = MongoPromptAuditWriter(
            client_factory=client_factory,
            queue_size=cfg.PROMPT_AUDIT_QUEUE_SIZE,
            workers=cfg.PROMPT_AUDIT_WORKERS,
        )
    elif backend == "postgres":
        raise NotImplementedError(
            "PROMPT_AUDIT_BACKEND=postgres is reserved; not built in this spec"
        )
    else:
        raise ValueError(f"unknown PROMPT_AUDIT_BACKEND={backend!r}")

    atexit.register(_atexit_close, w)
    return w


def _atexit_close(w: PromptAuditWriter) -> None:
    try:
        w.close()
    except Exception:
        pass
