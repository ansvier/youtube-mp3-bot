import asyncio
import importlib
import json
import time

import pytest
from aiogram.exceptions import TelegramConflictError, TelegramNetworkError
from aiogram.methods import GetMe, GetUpdates
from test_bot_entrypoint import cli


def test_healthcheck_uses_temp_dir_and_fails_on_missing_stale_future_or_invalid(tmp_path):
    marker = tmp_path / "health.json"
    assert cli(tmp_path, "--healthcheck", valid=False).returncode == 1
    for data in (
        {"updated_at": time.time() - 46, "worker": True},
        {"updated_at": time.time() + 100, "worker": True},
        {"updated_at": time.time(), "worker": False},
        {"updated_at": "invalid", "worker": True},
        {"updated_at": time.time(), "worker": True},
        {"updated_at": time.time(), "polling_at": time.time() - 46, "worker": True},
        {"updated_at": time.time(), "polling_at": time.time() + 100, "worker": True},
        {"updated_at": time.time(), "polling_at": "invalid", "worker": True},
    ):
        marker.write_text(json.dumps(data))
        assert cli(tmp_path, "--healthcheck", valid=False).returncode == 1
    marker.write_text(
        json.dumps(
            {
                "updated_at": time.time(),
                "polling_at": time.time(),
                "worker": True,
            }
        )
    )
    assert cli(tmp_path, "--healthcheck", valid=False).returncode == 0


@pytest.mark.asyncio
async def test_heartbeat_refreshes_only_from_live_event_loop_and_worker_health(tmp_path):
    module = importlib.import_module("mp3_bot.health")
    clock = [100.0]
    calls = 0

    class Worker:
        healthy = True

        async def health(self):
            nonlocal calls
            calls += 1
            return self.healthy

    worker = Worker()
    marker = module.HealthMarker(tmp_path, clock=lambda: clock[0])

    async def success(bot, method):
        return []

    task = asyncio.create_task(marker.run(worker, interval=0.01))
    try:
        for _ in range(50):
            if calls:
                break
            await asyncio.sleep(0.01)
        assert not marker.is_healthy()
        await marker.observe_polling(success, None, GetMe())
        assert not marker.is_healthy()
        await marker.observe_polling(success, None, GetUpdates())
        await asyncio.sleep(0.03)
        assert marker.is_healthy()
        clock[0] = 146
        assert not marker.is_healthy()
        await asyncio.sleep(0.03)
        assert not marker.is_healthy()  # Heartbeat cannot renew stale polling.
        await marker.observe_polling(success, None, GetUpdates())
        await asyncio.sleep(0.03)
        assert marker.is_healthy()
        worker.healthy = False
        await asyncio.sleep(0.03)
        assert not marker.is_healthy()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert not (tmp_path / "health.json").exists()


@pytest.mark.parametrize("error_type", [TelegramConflictError, TelegramNetworkError])
async def test_poll_failure_health_recovery_and_allowlisted_diagnostics(
    tmp_path, caplog, error_type
):
    from mp3_bot.health import HealthMarker

    clock = [100.0]
    marker = HealthMarker(tmp_path, clock=lambda: clock[0])

    class Worker:
        async def health(self):
            return True

    async def success(bot, method):
        return []

    method = GetUpdates()
    error = error_type(method=method, message="PRIVATE USER TEXT token=123456:" + "A" * 35)

    async def failure(bot, method):
        raise error

    task = asyncio.create_task(marker.run(Worker(), interval=0.01))
    try:
        await marker.observe_polling(success, None, method)
        await asyncio.sleep(0.03)
        assert marker.is_healthy()
        clock[0] = 120
        with pytest.raises(error_type) as caught:
            await marker.observe_polling(failure, None, method)
        assert caught.value is error
        assert marker.is_healthy() is (error_type is TelegramNetworkError)
        clock[0] = 146
        assert not marker.is_healthy()
        await asyncio.sleep(0.03)
        assert not marker.is_healthy()
        await marker.observe_polling(success, None, method)
        await asyncio.sleep(0.03)
        assert marker.is_healthy()
        records = [r for r in caplog.records if "telegram_poll_failed" in r.getMessage()]
        assert len(records) == 1
        expected = "conflict" if error_type is TelegramConflictError else "request_failed"
        assert records[0].getMessage() == f"telegram_poll_failed reason={expected}"
        assert records[0].exc_info is None
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert not list(tmp_path.iterdir())
