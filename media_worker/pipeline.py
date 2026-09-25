"""Per-job ownership keeps artifacts alive only while the consumer needs them."""

import asyncio
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from .config import MediaConfig
from .encoding import encode_source
from .errors import MediaError
from .extraction import Extractor
from .thumbnails import fetch_cover
from .urls import validate_url


class MediaPipeline:
    def __init__(self, config: MediaConfig, *, extractor=None, cover_fetcher=fetch_cover):
        self.config = config
        self.cover_fetcher = cover_fetcher
        self.extractor = extractor or Extractor(config)
        self._slots = asyncio.Semaphore(config.max_concurrent)
        self._tasks = set()
        self._closed = False
        config.temp_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

    @asynccontextmanager
    async def _job(self):
        if self._closed or self._slots.locked():
            raise MediaError("busy")
        await self._slots.acquire()
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            with tempfile.TemporaryDirectory(prefix="job-", dir=self.config.temp_dir) as name:
                directory = Path(name).resolve()  # noqa: ASYNC240 - local tmpfs, lifecycle-owned
                cookies = None
                if self.config.cookies_file:
                    cookies = directory / "cookies.txt"
                    shutil.copyfile(self.config.cookies_file, cookies)
                    cookies.chmod(0o600)
                yield directory, cookies
        finally:
            self._tasks.discard(task)
            self._slots.release()

    async def info(self, url: str):
        url = validate_url(url)
        async with self._job() as (directory, cookies):
            try:
                async with asyncio.timeout(self.config.download_timeout):
                    return (await self.extractor.info(url, directory, cookies)).info
            except TimeoutError:
                raise MediaError("timeout") from None

    @asynccontextmanager
    async def convert(self, url: str):
        url = validate_url(url)
        async with self._job() as (directory, cookies):
            try:
                async with asyncio.timeout(self.config.download_timeout):
                    extraction = await self.extractor.info(url, directory, cookies)
                    source = await self.extractor.download(url, directory, cookies)
            except TimeoutError:
                raise MediaError("timeout") from None
            try:
                async with asyncio.timeout(10):
                    cover = await self.cover_fetcher(extraction.thumbnail)
            except Exception:
                # Cover art is optional; never expose diagnostics or delay a valid MP3.
                cover = None
            yield await encode_source(source, extraction.info, self.config, cover=cover)

    async def close(self):
        self._closed = True
        tasks = self._tasks - {asyncio.current_task()}
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
