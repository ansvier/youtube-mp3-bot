"""Event-loop heartbeat, never a marker written merely on process startup."""

import asyncio
import json
import logging
import time
from pathlib import Path

from aiogram.exceptions import TelegramConflictError
from aiogram.methods import GetUpdates

log = logging.getLogger(__name__)


class HealthMarker:
    def __init__(self, directory: Path, *, clock=time.time):
        self.path = directory / "health.json"
        self.clock = clock
        self.last_poll_success = None
        self.poll_changed = asyncio.Event()

    async def observe_polling(self, make_request, bot, method):
        """Session middleware sees outcomes before aiogram's retry loop consumes them."""
        if not isinstance(method, GetUpdates):
            return await make_request(bot, method)
        try:
            result = await make_request(bot, method)
        except Exception as error:
            conflict = isinstance(error, TelegramConflictError)
            if conflict:
                self.last_poll_success = None
                self.clear()
            # Never log the exception, upstream description, method or update data.
            log.error(
                "telegram_poll_failed reason=%s", "conflict" if conflict else "request_failed"
            )
            raise
        self.last_poll_success = self.clock()
        self.poll_changed.set()
        return result

    def clear(self):
        self.path.unlink(missing_ok=True)

    def is_healthy(self) -> bool:
        try:
            if self.path.stat().st_size > 4096:
                return False
            payload = json.loads(self.path.read_text())
            timestamp = payload["updated_at"]
            polling_at = payload["polling_at"]
            return (
                type(timestamp) in (int, float)
                and 0 <= self.clock() - timestamp <= 45
                and type(polling_at) in (int, float)
                and 0 <= self.clock() - polling_at <= 45
                and payload.get("worker") is True
            )
        except (OSError, ValueError, TypeError, KeyError):
            return False

    async def run(self, worker, *, interval: float = 10):
        try:
            while True:
                try:
                    async with asyncio.timeout(6):
                        healthy = await worker.health()
                    if (
                        healthy
                        and self.last_poll_success is not None
                        and 0 <= self.clock() - self.last_poll_success <= 45
                    ):
                        self.path.parent.mkdir(parents=True, exist_ok=True)
                        temporary = self.path.with_suffix(".new")
                        temporary.write_text(
                            json.dumps(
                                {
                                    "updated_at": self.clock(),
                                    "polling_at": self.last_poll_success,
                                    "worker": True,
                                }
                            )
                        )
                        temporary.replace(self.path)
                    else:
                        self.clear()
                except Exception:
                    self.clear()
                    log.exception("Health heartbeat failed")
                try:
                    await asyncio.wait_for(self.poll_changed.wait(), interval)
                except TimeoutError:
                    pass
                self.poll_changed.clear()
        finally:
            self.clear()
