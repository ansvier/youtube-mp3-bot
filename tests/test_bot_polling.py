"""Polling readiness/diagnostics through the real module entrypoint."""

import asyncio
import os
import signal
import sys

import pytest
from aiohttp import web
from test_bot import TOKEN
from test_bot_entrypoint import ROOT


@pytest.mark.parametrize("conflict", [False, True])
async def test_entrypoint_requires_successful_get_updates(tmp_path, conflict):
    first_poll = asyncio.Event()
    permit_poll = asyncio.Event()
    second_poll = asyncio.Event()
    calls = []
    upstream_secret = "PRIVATE UPSTREAM DESCRIPTION AND USER TEXT"

    async def telegram(request):
        method = request.match_info["method"]
        calls.append(method)
        if method == "getMe":
            return web.json_response(
                {
                    "ok": True,
                    "result": {
                        "id": 123456,
                        "is_bot": True,
                        "first_name": "Test",
                    },
                }
            )
        assert method == "getUpdates"  # No implicit deleteWebhook side effect.
        first_poll.set()
        await permit_poll.wait()
        if calls.count("getUpdates") >= 2:
            second_poll.set()
        if conflict:
            return web.json_response(
                {
                    "ok": False,
                    "error_code": 409,
                    "description": f"{upstream_secret} {TOKEN}",
                },
                status=409,
            )
        await asyncio.sleep(0.05)
        return web.json_response({"ok": True, "result": []})

    async def health(request):
        return web.json_response({"status": "ok"})

    app = web.Application()
    app.router.add_post("/bot{token}/{method}", telegram)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    endpoint = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "BOT_TOKEN": TOKEN,
        "ALLOWED_USER_IDS": "10",
        "TEMP_DIR": str(tmp_path),
        "TELEGRAM_API_BASE_URL": endpoint,
        "MEDIA_WORKER_URL": endpoint,
        "LOG_LEVEL": "DEBUG",
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "mp3_bot",
        env=env,
        cwd=tmp_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def healthcheck():
        check = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "mp3_bot",
            "--healthcheck",
            env=env,
            cwd=tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(check.communicate(), 5)
        return check.returncode

    try:
        await asyncio.wait_for(first_poll.wait(), 8)
        # getMe succeeded, but a pending getUpdates must NOT confer readiness.
        assert await healthcheck() == 1
        permit_poll.set()
        await asyncio.wait_for(second_poll.wait(), 5)
        assert await healthcheck() == (1 if conflict else 0)
        process.send_signal(signal.SIGTERM)
        stdout, stderr = await asyncio.wait_for(process.communicate(), 8)
        assert process.returncode == 0, (stdout + stderr).decode()
        output = (stdout + stderr).decode()
        if conflict:
            assert "telegram_poll_failed reason=conflict" in output
        assert TOKEN not in output
        assert upstream_secret not in output
        assert "deleteWebhook" not in calls
        assert not list(tmp_path.iterdir())
    finally:
        permit_poll.set()
        if process.returncode is None:
            process.kill()
            await process.communicate()
        await runner.cleanup()
