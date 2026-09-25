import asyncio
import json
import os
import sys

import aiohttp
import pytest
from aiohttp import web
from test_bot import TOKEN, URL, settings, update
from test_bot_client import META, header
from test_bot_entrypoint import ROOT


@pytest.mark.asyncio
@pytest.mark.parametrize("duration,telegram_seconds", [(12, "12"), (12.25, "13"), (None, None)])
async def test_real_send_audio_is_multipart_with_named_bytes_and_tags(
    tmp_path, duration, telegram_seconds
):
    from mp3_bot.__main__ import create_bot
    from mp3_bot.app import BotRuntime
    from mp3_bot.client import WorkerClient

    uploads = []

    async def api(request):
        if request.match_info["method"] == "sendAudio":
            fields = {}
            assert request.content_type == "multipart/form-data"
            reader = await request.multipart()
            async for part in reader:
                if part.filename:
                    fields["file"] = (part.filename, await part.read())
                else:
                    fields[part.name] = await part.text()
            uploads.append(fields)
        return web.json_response(
            {
                "ok": True,
                "result": {
                    "message_id": 99,
                    "date": 1700000000,
                    "chat": {"id": 10, "type": "private"},
                },
            }
        )

    async def media(request):
        assert await request.json() == {"url": "https://www.youtube.com/watch?v=abcdefghijk"}
        if request.path == "/info":
            return web.json_response({"title": "Preview", "performer": "Preview", "duration": 99})
        return web.Response(
            body=b"ID3 actual fixture",
            content_type="audio/mpeg",
            headers={"X-Media-Info": header({**META, "duration": duration})},
        )

    app = web.Application()
    app.router.add_post("/bot{token}/{method}", api)
    app.router.add_post("/info", media)
    app.router.add_post("/convert", media)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    config = settings(tmp_path, TELEGRAM_API_BASE_URL=url, MEDIA_WORKER_URL=url)
    bot = create_bot(config)
    try:
        async with aiohttp.ClientSession() as session:
            runtime = BotRuntime(config, bot, WorkerClient(config, session))
            await runtime.start()
            try:
                await runtime.dispatcher.feed_update(bot, update(URL))
                await asyncio.wait_for(runtime.queue.join(), 3)
            finally:
                await runtime.close()
        assert len(uploads) == 1
        assert uploads[0]["file"] == (META["filename"], b"ID3 actual fixture")
        assert uploads[0]["title"] == META["title"]
        assert uploads[0]["performer"] == META["performer"]
        assert uploads[0].get("duration") == telegram_seconds
        assert uploads[0]["audio"].startswith("attach://")
        assert not list(tmp_path.iterdir())
    finally:
        await bot.session.close()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_failed_get_me_never_marks_ready_and_redacts_traceback(tmp_path):
    async def denied(request):
        return web.json_response(
            {"ok": False, "error_code": 401, "description": "Unauthorized " + TOKEN}, status=401
        )

    app = web.Application()
    app.router.add_post("/bot{token}/getMe", denied)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    (tmp_path / "health.json").write_text(json.dumps({"updated_at": 0, "worker": True}))
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
        stdout, stderr = await asyncio.wait_for(process.communicate(), 8)
        assert process.returncode == 1
        assert b"Traceback" in stdout
        assert b"TelegramUnauthorizedError" in stdout
        assert TOKEN.encode() not in stdout + stderr
        assert not list(tmp_path.iterdir())
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
        await runner.cleanup()
