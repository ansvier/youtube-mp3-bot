import asyncio
import base64
import importlib
import json
from contextlib import asynccontextmanager

import aiohttp
import pytest
from aiohttp import web
from test_bot import CANONICAL, settings

META = {
    "title": "Песня",
    "performer": "Автор",
    "duration": 12,
    "filename": "Песня.mp3",
    "bitrate": 192,
}


@pytest.mark.asyncio
async def test_worker_post_timeout_is_bounded_and_not_retried(tmp_path):
    from media_worker.errors import MediaError
    from mp3_bot.client import WorkerClient

    release = asyncio.Event()

    async def stalled(request):
        await release.wait()
        return web.json_response(META)

    async with worker_server(info=stalled) as (url, calls), aiohttp.ClientSession() as session:
        client = WorkerClient(
            settings(tmp_path, MEDIA_WORKER_URL=url, DOWNLOAD_TIMEOUT="1"), session
        )
        try:
            with pytest.raises(MediaError) as error:
                await asyncio.wait_for(client.info(CANONICAL), 2)
            assert error.value.code == "worker_timeout"
            assert len(calls) == 1
        finally:
            release.set()


@pytest.mark.asyncio
async def test_worker_conversion_timeout_budget_includes_fallback_conversions(tmp_path):
    from mp3_bot.client import WorkerClient

    seen = []
    async with worker_server() as (url, calls), aiohttp.ClientSession() as session:

        class RecordingSession:
            def post(self, *args, **kwargs):
                seen.append(kwargs)
                return session.post(*args, **kwargs)

        client = WorkerClient(settings(tmp_path, MEDIA_WORKER_URL=url), RecordingSession())
        await client.info(CANONICAL)
        await client.convert(CANONICAL, tmp_path / "audio.mp3")
    assert seen[0]["timeout"].total <= 60
    assert seen[1]["timeout"].total == 600 + 4 * 300 + 60
    assert all(request["allow_redirects"] is False for request in seen)


def header(metadata=META):
    return base64.urlsafe_b64encode(json.dumps(metadata, ensure_ascii=False).encode()).decode()


@asynccontextmanager
async def worker_server(convert=None, info=None):
    calls = []

    async def handle(request):
        calls.append((request.path, await request.json()))
        response = info if request.path == "/info" else convert
        if callable(response):
            return await response(request)
        if response is not None:
            return response
        if request.path == "/info":
            return web.json_response(
                {"title": "Info title", "performer": "Info artist", "duration": 99}
            )
        return web.Response(
            body=b"ID3 audio", headers={"X-Media-Info": header()}, content_type="audio/mpeg"
        )

    app = web.Application()
    app.router.add_post("/info", handle)
    app.router.add_post("/convert", handle)

    async def healthy(request):
        return web.json_response({"status": "ok"})

    app.router.add_get("/health", healthy)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}", calls
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_client_accepts_actual_fractional_duration_and_unknown_preview(tmp_path):
    from mp3_bot.client import WorkerClient

    actual = {**META, "duration": 12.25}
    preview = web.json_response({"title": "Preview", "performer": "", "duration": None})
    converted = web.Response(
        body=b"ID3 audio", content_type="audio/mpeg", headers={"X-Media-Info": header(actual)}
    )
    async with (
        worker_server(info=preview, convert=converted) as (url, _),
        aiohttp.ClientSession() as session,
    ):
        client = WorkerClient(settings(tmp_path, MEDIA_WORKER_URL=url), session)
        assert (await client.info(CANONICAL))["duration"] is None
        assert (await client.convert(CANONICAL, tmp_path / "audio.mp3"))["duration"] == 12.25


@pytest.mark.asyncio
async def test_client_streams_multipart_source_locally_with_authoritative_metadata(tmp_path):
    module = importlib.import_module("mp3_bot.client")
    async with worker_server() as (url, calls), aiohttp.ClientSession() as session:
        client = module.WorkerClient(settings(tmp_path, MEDIA_WORKER_URL=url), session)
        assert (await client.info(CANONICAL))["title"] == "Info title"
        path = tmp_path / "audio.mp3"
        metadata = await client.convert(CANONICAL, path)
        assert metadata == META
        assert path.read_bytes() == b"ID3 audio"
        assert calls == [("/info", {"url": CANONICAL}), ("/convert", {"url": CANONICAL})]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers,body,content_type",
    [
        ({}, b"data", "audio/mpeg"),
        ({"X-Media-Info": "not-base64"}, b"data", "audio/mpeg"),
        ({"X-Media-Info": header({**META, "filename": "../outside.mp3"})}, b"data", "audio/mpeg"),
        ({"X-Media-Info": header({**META, "duration": -1})}, b"data", "audio/mpeg"),
        ({"X-Media-Info": header({**META, "duration": True})}, b"data", "audio/mpeg"),
        ({"X-Media-Info": header({**META, "title": "x" * 2000})}, b"data", "audio/mpeg"),
        ({"X-Media-Info": header({**META, "title": "bad\u0000title"})}, b"data", "audio/mpeg"),
        ({"X-Media-Info": header({**META, "filename": "bad\\path.mp3"})}, b"data", "audio/mpeg"),
        ({"X-Media-Info": header({**META, "bitrate": "192"})}, b"data", "audio/mpeg"),
        ({"X-Media-Info": header()}, b"data", "text/html"),
        ({"X-Media-Info": header()}, b"", "audio/mpeg"),
    ],
)
async def test_client_rejects_invalid_audio_contract(tmp_path, headers, body, content_type):
    from media_worker.errors import MediaError
    from mp3_bot.client import WorkerClient

    response = web.Response(body=body, headers=headers, content_type=content_type)
    async with worker_server(convert=response) as (url, calls), aiohttp.ClientSession() as session:
        client = WorkerClient(settings(tmp_path, MEDIA_WORKER_URL=url), session)
        with pytest.raises(MediaError) as error:
            await client.convert(CANONICAL, tmp_path / "audio.mp3")
        assert error.value.code == "invalid_response"
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_client_enforces_independent_byte_cap_even_without_content_length(tmp_path):
    from media_worker.errors import MediaError
    from mp3_bot.client import WorkerClient

    async def stream(request):
        response = web.StreamResponse(
            headers={"X-Media-Info": header(), "Content-Type": "audio/mpeg"}
        )
        await response.prepare(request)
        for _ in range(17):
            await response.write(b"x" * 65536)
        await response.write_eof()
        return response

    async with worker_server(convert=stream) as (url, calls), aiohttp.ClientSession() as session:
        client = WorkerClient(
            settings(tmp_path, MEDIA_WORKER_URL=url, MAX_FILE_SIZE_MB="1"), session
        )
        path = tmp_path / "audio.mp3"
        with pytest.raises(MediaError) as error:
            await client.convert(CANONICAL, path)
        assert error.value.code == "file_too_large"
        assert path.stat().st_size <= 1_000_000
        assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["info", "convert"])
async def test_worker_error_messages_are_not_trusted_or_retried(tmp_path, endpoint):
    from media_worker.errors import MediaError
    from mp3_bot.client import WorkerClient

    response = web.json_response(
        {"code": "private", "message": "SECRET arbitrary worker text"}, status=503
    )
    async with (
        worker_server(**{endpoint: response}) as (url, calls),
        aiohttp.ClientSession() as session,
    ):
        client = WorkerClient(settings(tmp_path, MEDIA_WORKER_URL=url), session)
        with pytest.raises(MediaError) as error:
            if endpoint == "info":
                await client.info(CANONICAL)
            else:
                await client.convert(CANONICAL, tmp_path / "audio.mp3")
        assert "SECRET" not in str(error.value)
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_redirects_are_not_followed_and_info_json_is_bounded(tmp_path):
    from media_worker.errors import MediaError
    from mp3_bot.client import WorkerClient

    for response in (
        web.Response(status=307, headers={"Location": "/convert"}),
        web.Response(body=b" " * 70000, content_type="application/json"),
    ):
        async with worker_server(info=response) as (url, calls), aiohttp.ClientSession() as session:
            client = WorkerClient(settings(tmp_path, MEDIA_WORKER_URL=url), session)
            with pytest.raises(MediaError):
                await client.info(CANONICAL)
            assert len(calls) == 1
