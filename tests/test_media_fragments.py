"""Real yt-dlp HLS transport, using only locally generated audio."""

import json
import shutil

import pytest
from aiohttp import web

from media_worker import extraction
from media_worker.config import MediaConfig
from media_worker.errors import MediaError
from media_worker.pipeline import MediaPipeline
from media_worker.process import run_process

URL = "https://www.youtube.com/watch?v=abcdefghijk"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
@pytest.mark.parametrize("missing_fragments", [False, True])
async def test_real_hls_never_publishes_incomplete_audio(tmp_path, monkeypatch, missing_fragments):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    await run_process(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=8",
            "-c:a",
            "aac",
            "-f",
            "hls",
            "-hls_time",
            "1",
            "-hls_list_size",
            "0",
            str(fixture / "audio.m3u8"),
        ],
        cwd=fixture,
        timeout=10,
    )
    fragments = sorted(fixture.glob("*.ts"))
    assert len(fragments) >= 8
    missing = {p.name for p in fragments[-2:]} if missing_fragments else set()
    requests = []

    async def serve(request):
        name = request.match_info["name"]
        requests.append(name)
        if name in missing:
            raise web.HTTPNotFound()
        return web.FileResponse(fixture / name)

    app = web.Application()
    app.router.add_get("/{name}", serve)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    local_url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/audio.m3u8"
    metadata = fixture / "info.json"
    metadata.write_text(
        json.dumps(
            {
                "id": "synthetic",
                "title": "Synthetic tone",
                "duration": 8,
                "url": local_url,
                "ext": "mp4",
                "protocol": "m3u8_native",
                "vcodec": "none",
                "acodec": "aac",
                "extractor": "generic",
                "extractor_key": "Generic",
                "webpage_url": local_url,
            }
        )
    )

    async def local_acquisition(args, **kwargs):
        # Keep validation and ALL production downloader flags; replace only
        # YouTube acquisition metadata with a local, synthetic transport fixture.
        assert args[-2:] == ["--", URL]
        return await run_process(args[:-2] + ["--load-info-json", str(metadata)], **kwargs)

    monkeypatch.setattr(extraction, "run_process", local_acquisition)
    root = tmp_path / "jobs"
    pipeline = MediaPipeline(MediaConfig(temp_dir=root))
    results = []
    try:
        if missing_fragments:
            with pytest.raises(MediaError) as error:
                async with pipeline.convert(URL) as result:
                    results.append(result)
            assert error.value.code == "download_failed"
            assert not results
            assert any(name in missing for name in requests)
        else:
            async with pipeline.convert(URL) as result:
                assert result.path.is_file()
                assert result.info.duration >= 8
            assert all(p.name in requests for p in fragments)
    finally:
        await pipeline.close()
        await runner.cleanup()
        assert not list(root.iterdir())
