import asyncio
import shutil

import pytest
from test_media_encoding import synthetic_media as synthetic_media

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


class FixtureExtractor:
    def __init__(self, source):
        self.source = source
        self.calls = 0

    async def info(self, url, directory, cookies=None):
        from media_worker.extraction import Extraction
        from media_worker.models import MediaInfo

        self.calls += 1
        if cookies:
            assert cookies.parent == directory
            cookies.write_text("modified by extractor")
        return Extraction(MediaInfo(f"Песня {self.calls}", "Исполнитель", None), None)

    async def download(self, url, directory, cookies=None):
        target = directory / "source.media"
        shutil.copyfile(self.source, target)
        return target


@pytest.mark.asyncio
async def test_pipeline_reextracts_copies_cookies_and_cleans_success(synthetic_media, tmp_path):
    from media_worker.config import MediaConfig
    from media_worker.pipeline import MediaPipeline

    source, _ = synthetic_media
    cookies = tmp_path / "original-cookies.txt"
    cookies.write_text("original")
    root = tmp_path / "jobs"
    pipeline = MediaPipeline(
        MediaConfig(temp_dir=root, cookies_file=cookies), extractor=FixtureExtractor(source)
    )
    info = await pipeline.info(URL)
    assert info.title == "Песня 1"
    assert list(root.iterdir()) == []
    async with pipeline.convert(URL) as result:
        assert result.info.title == "Песня 2"
        assert result.path.is_file()
        assert len(list(root.iterdir())) == 1
    assert cookies.read_text() == "original"
    assert not result.path.exists()
    assert list(root.iterdir()) == []
    await pipeline.close()


@pytest.mark.asyncio
async def test_pipeline_cleans_on_consumer_error(synthetic_media, tmp_path):
    from media_worker.config import MediaConfig
    from media_worker.pipeline import MediaPipeline

    root = tmp_path / "jobs"
    pipeline = MediaPipeline(
        MediaConfig(temp_dir=root), extractor=FixtureExtractor(synthetic_media[0])
    )
    with pytest.raises(RuntimeError):
        async with pipeline.convert(URL):
            raise RuntimeError("client disconnected")
    assert list(root.iterdir()) == []
    await pipeline.close()


@pytest.mark.asyncio
async def test_pipeline_capacity_rejects_instead_of_unbounded_queue(tmp_path):
    from media_worker.config import MediaConfig
    from media_worker.errors import MediaError
    from media_worker.pipeline import MediaPipeline

    ready = asyncio.Event()

    class WaitingExtractor:
        async def info(self, *args):
            ready.set()
            await asyncio.Event().wait()

    root = tmp_path / "jobs"
    pipeline = MediaPipeline(MediaConfig(temp_dir=root), extractor=WaitingExtractor())
    task = asyncio.create_task(pipeline.info(URL))
    await ready.wait()
    try:
        with pytest.raises(MediaError) as error:
            await asyncio.wait_for(pipeline.info(URL), timeout=0.1)
        assert error.value.code == "busy"
        await pipeline.close()
        assert task.cancelled()
        assert list(root.iterdir()) == []
        with pytest.raises(MediaError) as error:
            await asyncio.wait_for(pipeline.info(URL), timeout=0.1)
        assert error.value.code == "busy"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_pipeline_download_budget_is_total_not_per_stage(synthetic_media, tmp_path):
    from media_worker.config import MediaConfig
    from media_worker.errors import MediaError
    from media_worker.pipeline import MediaPipeline

    class SlowExtractor(FixtureExtractor):
        async def info(self, *args):
            await asyncio.sleep(0.04)
            return await super().info(*args)

        async def download(self, *args):
            await asyncio.sleep(0.04)
            return await super().download(*args)

    config = MediaConfig(temp_dir=tmp_path / "jobs", download_timeout=0.06)
    pipeline = MediaPipeline(config, extractor=SlowExtractor(synthetic_media[0]))
    with pytest.raises(MediaError) as error:
        async with pipeline.convert(URL):
            pass
    assert error.value.code == "timeout"
    assert list(config.temp_dir.iterdir()) == []
    await pipeline.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("shutdown", [False, True])
async def test_pipeline_cancel_or_shutdown_cleans_child_and_temp(tmp_path, shutdown):
    import os
    import sys

    from media_worker.config import MediaConfig
    from media_worker.pipeline import MediaPipeline
    from media_worker.process import run_process

    ready = asyncio.Event()
    pid = None

    class ProcessExtractor:
        async def info(self, url, directory, cookies=None):
            nonlocal pid
            task = asyncio.create_task(
                run_process(
                    [
                        sys.executable,
                        "-c",
                        'import os,time; from pathlib import Path; Path("pid").write_text(str(os.getpid())); time.sleep(2)',
                    ],
                    cwd=directory,
                    timeout=5,
                )
            )
            try:
                for _ in range(200):
                    if (directory / "pid").exists():
                        break
                    await asyncio.sleep(0.01)
                pid = int((directory / "pid").read_text())
                ready.set()
                await task
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    config = MediaConfig(temp_dir=tmp_path / "jobs")
    pipeline = MediaPipeline(config, extractor=ProcessExtractor())
    task = asyncio.create_task(pipeline.info(URL))
    await ready.wait()
    try:
        if shutdown:
            await pipeline.close()
        else:
            task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert list(config.temp_dir.iterdir()) == []
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await pipeline.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("cover_failure", [False, True])
async def test_pipeline_cover_is_optional_and_embedded(synthetic_media, tmp_path, cover_failure):
    from mutagen.id3 import ID3

    from media_worker.config import MediaConfig
    from media_worker.pipeline import MediaPipeline

    async def get_cover(url):
        if cover_failure:
            raise OSError("thumbnail network failed")
        return synthetic_media[1].read_bytes()

    pipeline = MediaPipeline(
        MediaConfig(temp_dir=tmp_path / "jobs"),
        extractor=FixtureExtractor(synthetic_media[0]),
        cover_fetcher=get_cover,
    )
    async with pipeline.convert(URL) as result:
        assert bool(ID3(result.path).getall("APIC")) is not cover_failure
    await pipeline.close()
