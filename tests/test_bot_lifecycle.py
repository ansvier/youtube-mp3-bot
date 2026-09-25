import asyncio
import os
import signal
import sys

import pytest
from aiohttp import web
from test_bot import TOKEN, URL, update
from test_bot_client import META, header
from test_bot_entrypoint import ROOT


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_signal", [signal.SIGTERM, signal.SIGINT])
async def test_real_polling_heartbeat_and_signal_cancel_clean_partial_file(tmp_path, stop_signal):
    convert_started = asyncio.Event()
    release = asyncio.Event()
    served_update = False
    calls = []

    async def telegram(request):
        nonlocal served_update
        method = request.match_info["method"]
        calls.append(method)
        if method == "getMe":
            result = {
                "id": 123456,
                "is_bot": True,
                "first_name": "Test",
                "username": "private_test_bot",
            }
        elif method == "getUpdates":
            if not served_update:
                served_update = True
                result = [update(URL).model_dump(mode="json", exclude_none=True)]
            else:
                await release.wait()
                result = []
        else:
            result = {"message_id": 99, "date": 1700000000, "chat": {"id": 10, "type": "private"}}
        return web.json_response({"ok": True, "result": result})

    async def info(request):
        return web.json_response({key: META[key] for key in ("title", "performer", "duration")})

    async def convert(request):
        response = web.StreamResponse(
            headers={"X-Media-Info": header(), "Content-Type": "audio/mpeg"}
        )
        await response.prepare(request)
        # Exceed Python 3.14's buffered file-write threshold before SIGTERM.
        await response.write(b"ID3" + b"x" * 262144)
        convert_started.set()
        await release.wait()
        return response

    async def health(request):
        return web.json_response({"status": "ok"})

    app = web.Application()
    app.router.add_post("/bot{token}/{method}", telegram)
    app.router.add_post("/info", info)
    app.router.add_post("/convert", convert)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "BOT_TOKEN": TOKEN,
        "ALLOWED_USER_IDS": "10",
        "TEMP_DIR": str(tmp_path),
        "TELEGRAM_API_BASE_URL": url,
        "MEDIA_WORKER_URL": url,
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
    try:
        await asyncio.wait_for(convert_started.wait(), 8)
        async with asyncio.timeout(5):
            # The observed files belong to another process; no asyncio Event can signal writes.
            while not (tmp_path / "health.json").exists() or not any(  # noqa: ASYNC110
                path.stat().st_size for path in tmp_path.glob("job-*/audio.mp3")
            ):
                await asyncio.sleep(0.02)
        assert "getMe" in calls and "getUpdates" in calls
        process.send_signal(stop_signal)
        stdout, stderr = await asyncio.wait_for(process.communicate(), 8)
        assert process.returncode == 0, (stdout + stderr).decode()
        assert TOKEN.encode() not in stdout + stderr
        assert not list(tmp_path.iterdir())
        assert "sendAudio" not in calls
    except Exception:
        if process.returncode is None:
            process.kill()
        stdout, stderr = await process.communicate()
        print(
            "PROCESS DIAGNOSTICS",
            (stdout + stderr).decode(),
            [(str(p.relative_to(tmp_path)), p.stat().st_size) for p in tmp_path.rglob("*")],
        )
        raise
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
        release.set()
        await runner.cleanup()
