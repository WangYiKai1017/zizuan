"""Short-lived in-process locks for knowledge-base filesystem commits."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, ClassVar


class UserKBLockManager:
    """Serialize brief filesystem snapshots and commits for one user KB.

    Long-running LLM and image-generation work must happen outside this lock.
    The lock is process-local, matching the current SessionManager deployment
    model.
    """

    _instance: ClassVar["UserKBLockManager | None"] = None

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    @classmethod
    def get_instance(cls) -> "UserKBLockManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton for isolated tests."""
        cls._instance = None

    @staticmethod
    def _key(kb_path: str | Path) -> str:
        return str(Path(kb_path).expanduser().resolve())

    @asynccontextmanager
    async def hold(self, kb_path: str | Path) -> AsyncIterator[None]:
        """Hold the lock for one short snapshot or commit operation."""
        lock = self._locks.setdefault(self._key(kb_path), asyncio.Lock())
        async with lock:
            yield
