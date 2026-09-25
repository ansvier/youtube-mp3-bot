"""Real service + converter + client + aiogram; ONLY acquisition/API are synthetic."""

import asyncio
import io
import math
import shutil
import struct
import wave

import aiohttp
import pytest
from aiogram import Bot
from aiogram.methods import SendAudio
from aiohttp import web
from mutagen.id3 import ID3
from mutagen.mp3 import MP3
from test_bot import TOKEN, TelegramSession, settings, update

from media_worker.config import MediaConfig
from media_worker.extraction import Extraction
from media_worker.models import MediaInfo
from media_worker.pipeline import MediaPipeline
from media_worker.service import create_app
from mp3_bot.app import BotRuntime
from mp3_bot.client import WorkerClient


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
@pytest.mark.parametrize("source_duration", [1.25, None])
async def test_real_worker_to_dispatcher_mp3_and_cleanup(tmp_path, source_duration):
    worker_root = tmp_path / "worker"
    bot_root = tmp_path / "bot"

    class GeneratedAudio:
        async def info(self, url, directory, cookies):
            return Extraction(
                MediaInfo("Собственный тест — Звук", "Тестовый автор", source_duration), None
            )

        async def download(self, url, directory, cookies):
            path = directory / "source.wav"
            with wave.open(str(path), "wb") as output:
                output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                output.writeframes(
                    b"".join(
                        struct.pack("<h", int(5000 * math.sin(2 * math.pi * 440 * i / 16000)))
                        for i in range(20000)
                    )
                )
            return path

    async def no_cover(url):
        return None

    pipeline = MediaPipeline(
        MediaConfig(temp_dir=worker_root), extractor=GeneratedAudio(), cover_fetcher=no_cover
    )
    runner = web.AppRunner(create_app(pipeline=pipeline), handler_cancellation=True)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    endpoint = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    telegram = TelegramSession()
    bot = Bot(TOKEN, session=telegram)
    try:
        async with aiohttp.ClientSession(trust_env=False) as session:
            config = settings(bot_root, MEDIA_WORKER_URL=endpoint)
            runtime = BotRuntime(config, bot, WorkerClient(config, session))
            await runtime.start()
            try:
                await runtime.dispatcher.feed_update(
                    bot, update("Вот аудио https://youtu.be/abcdefghijk?list=ignore")
                )
                await asyncio.wait_for(runtime.queue.join(), 30)
            finally:
                await runtime.close()
        sends = [call for call in telegram.calls if isinstance(call, SendAudio)]
        assert len(sends) == 1, [getattr(c, "text", "") for c in telegram.calls]
        sent = sends[0]
        assert sent.title == "Собственный тест — Звук"
        assert sent.performer == "Тестовый автор"
        assert sent.audio.filename == "Собственный тест — Звук.mp3"
        assert sent.duration == 2  # ceil(actual FFmpeg output seconds)
        audio = telegram.audio_bytes[0]
        tags = ID3(io.BytesIO(audio))
        assert tags["TIT2"].text == [sent.title]
        assert tags["TPE1"].text == [sent.performer]
        probe = MP3(io.BytesIO(audio))
        assert 1.2 <= probe.info.length <= 1.5
        assert probe.info.bitrate == 192000
        assert not list(worker_root.iterdir())
        assert not list(bot_root.iterdir())
    finally:
        await bot.session.close()
        await runner.cleanup()
