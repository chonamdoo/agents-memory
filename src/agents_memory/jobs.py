from __future__ import annotations

import asyncio
import logging

from .config import Settings
from .domain import DomainError
from .store import Store

logger = logging.getLogger(__name__)


class CleanupScheduler:
    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._scheduling = False
        self.last_error: str | None = None
        self.last_result: dict | None = None

    @property
    def status(self) -> dict:
        return {
            "running": self._task is not None and not self._task.done(),
            "scheduling": self._scheduling,
            "last_error": self.last_error,
            "last_result": self.last_result,
        }

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self.run(), name="agents-memory-cleanup-scheduler")

    async def run(self) -> None:
        while not self._stop.is_set():
            self._scheduling = True
            more = False
            try:
                self.last_result = await self.store.schedule_cleanup()
                self.last_error = None
                more = self.last_result.get("more", False) is True
            except DomainError as error:
                self.last_error = error.code
                logger.warning(
                    "Cleanup scheduling failed: operation=schedule_cleanup exception_type=%s",
                    type(error).__name__,
                )
            except Exception as error:
                self.last_error = "CLEANUP_AUTHORITY_UNAVAILABLE"
                logger.warning(
                    "Cleanup scheduling failed: operation=schedule_cleanup exception_type=%s",
                    type(error).__name__,
                )
            finally:
                self._scheduling = False

            if more:
                await asyncio.sleep(0)
                continue
            try:
                await asyncio.wait_for(
                    self._stop.wait(), self.settings.cleanup_interval_seconds
                )
            except TimeoutError:
                continue

    async def stop(self, timeout: float = 30) -> dict:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._task), timeout)
            except TimeoutError:
                return {"local_drained": False, "scheduling": self._scheduling,
                        "durable_work_recoverable": True}
        return {"local_drained": True, "scheduling": False, "durable_work_recoverable": True}
