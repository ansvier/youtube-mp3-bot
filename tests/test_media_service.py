import base64
import json

import pytest
from aiohttp.test_utils import TestClient, TestServer
from mutagen.id3 import ID3
from test_media_encoding import synthetic_media as synthetic_media
from test_media_pipeline import FixtureExtractor

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.mark.asyncio
async def test_http_health_info_and_real_mp3_contract(synthetic_media, tmp_path):
    from media_worker.config import MediaConfig
    from media_worker.pipeline import MediaPipeline
    from media_worker.service import create_app

    config = MediaConfig(temp_dir=tmp_path / "jobs")
    pipeline = MediaPipeline(config, extractor=FixtureExtractor(synthetic_media[0]))
    async with TestClient(
        TestServer(create_app(config, pipeline=pipeline), handler_cancellation=True)
    ) as client:
        response = await client.get("/health")
        assert response.status == 200 and await response.json() == {"status": "ok"}
        response = await client.post("/info", json={"url": URL})
        assert response.status == 200
        assert await response.json() == {
            "title": "Песня 1",
            "performer": "Исполнитель",
            "duration": None,
        }
        response = await client.post("/convert", json={"url": URL})
        assert response.status == 200
        assert response.content_type == "audio/mpeg"
        header = response.headers["X-Media-Info"]
        assert len(header) < 4096
        info = json.loads(base64.urlsafe_b64decode(header))
        assert set(info) == {"title", "performer", "duration", "filename", "bitrate"}
        assert info["title"] == "Песня 2" and info["bitrate"] == 192
        assert info["filename"] == "Песня 2.mp3"
        assert 2.9 <= info["duration"] <= 3.2
        path = tmp_path / "received.mp3"
        path.write_bytes(await response.read())
        assert path.stat().st_size == int(response.headers["Content-Length"])
        assert ID3(path)["TIT2"].text == ["Песня 2"]
    assert list(config.temp_dir.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"url": "https://example.com/secret"},
        {"url": URL, "args": "--exec bad"},
        {"url": ["not-a-string"]},
        [],
        None,
        {"url": "x" * 10000},
    ],
)
async def test_http_rejects_bad_payload_with_small_safe_json(tmp_path, body):
    from media_worker.config import MediaConfig
    from media_worker.service import create_app

    async with TestClient(
        TestServer(create_app(MediaConfig(temp_dir=tmp_path / "jobs")))
    ) as client:
        response = await client.post("/convert", json=body)
        assert response.status == 400
        payload = await response.json()
        assert set(payload) == {"code", "message"}
        assert len(payload["message"]) < 300
        assert "/secret" not in payload["message"]
        assert str(tmp_path) not in payload["message"]


@pytest.mark.asyncio
async def test_http_disconnect_cancels_child_and_releases_capacity(tmp_path):
    import asyncio
    import os
    import sys

    from media_worker.config import MediaConfig
    from media_worker.pipeline import MediaPipeline
    from media_worker.process import run_process
    from media_worker.service import create_app

    class ChildExtractor:
        async def info(self, url, directory, cookies=None):
            await run_process(
                [
                    sys.executable,
                    "-c",
                    'import os,time; from pathlib import Path; Path("pid").write_text(str(os.getpid())); time.sleep(5)',
                ],
                cwd=directory,
                timeout=6,
            )

    config = MediaConfig(temp_dir=tmp_path / "jobs")
    pipeline = MediaPipeline(config, extractor=ChildExtractor())
    async with TestClient(TestServer(create_app(config, pipeline=pipeline))) as client:
        _, writer = await asyncio.open_connection(client.server.host, client.server.port)
        body = json.dumps({"url": URL}).encode()
        writer.write(
            b"POST /info HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode()
            + body
        )
        await writer.drain()
        try:
            for _ in range(100):
                pids = list(config.temp_dir.glob("job-*/pid"))
                if pids:
                    break
                await asyncio.sleep(0.01)
            assert pids
            pid = int(pids[0].read_text())
            response = await client.post("/info", json={"url": URL})
            assert response.status == 400 and (await response.json())["code"] == "busy"
            assert len(list(config.temp_dir.iterdir())) == 1
            writer.close()
            await writer.wait_closed()
            for _ in range(100):
                if not list(config.temp_dir.iterdir()):
                    break
                await asyncio.sleep(0.01)
            assert list(config.temp_dir.iterdir()) == []
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
            # Capacity is released before app shutdown, not just at server cleanup.
            assert not pipeline._slots.locked()
        finally:
            writer.close()
            await writer.wait_closed()


@pytest.mark.asyncio
async def test_stream_disconnect_cleans_response_file(tmp_path):
    import asyncio
    import tempfile
    from contextlib import asynccontextmanager
    from pathlib import Path

    from media_worker.config import MediaConfig
    from media_worker.models import ConvertedMedia, MediaInfo
    from media_worker.service import create_app

    finished = asyncio.Event()

    class TransportFixturePipeline:
        @asynccontextmanager
        async def convert(self, url):
            # Sparse payload exercises backpressure only; actual MP3 verified separately.
            with tempfile.TemporaryDirectory(dir=tmp_path) as name:
                path = Path(name) / "transport-fixture"
                with path.open("wb") as stream:
                    stream.truncate(64_000_000)
                try:
                    yield ConvertedMedia(path, MediaInfo("x", "", 1), "x.mp3", 192)
                finally:
                    finished.set()

        async def close(self):
            pass

    async with TestClient(
        TestServer(create_app(MediaConfig(temp_dir=tmp_path), pipeline=TransportFixturePipeline()))
    ) as client:
        reader, writer = await asyncio.open_connection(client.server.host, client.server.port)
        body = json.dumps({"url": URL}).encode()
        writer.write(
            b"POST /convert HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode()
            + body
        )
        await writer.drain()
        await reader.readuntil(b"\r\n\r\n")
        writer.close()
        await writer.wait_closed()
        await asyncio.wait_for(finished.wait(), timeout=2)
        assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_internal_exceptions_do_not_leak_to_http_or_logs(tmp_path, caplog):
    from media_worker.config import MediaConfig
    from media_worker.service import create_app

    class BrokenPipeline:
        async def info(self, url):
            raise RuntimeError(
                "SECRET cookie=/private/secret URL=https://youtube.com/?token=SECRET"
            )

        async def close(self):
            pass

    async with TestClient(
        TestServer(create_app(MediaConfig(temp_dir=tmp_path), pipeline=BrokenPipeline()))
    ) as client:
        response = await client.post("/info", json={"url": URL})
        assert response.status == 400
        assert (await response.json())["code"] == "processing_failed"
        assert "SECRET" not in await response.text()
    assert "SECRET" not in caplog.text
    assert "/private/secret" not in caplog.text
    assert "traceback=" in caplog.text and "exception=RuntimeError" in caplog.text
