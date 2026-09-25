import asyncio
from contextlib import asynccontextmanager

import aiohttp
import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText, SendMessage
from aiohttp import web
from test_bot import CANONICAL, TOKEN, URL, FixtureWorker, TelegramSession, settings, update


@pytest.mark.asyncio
@pytest.mark.parametrize("duration", [12.25, None, 0])
async def test_client_consumes_real_worker_http_schema(tmp_path, duration):
    from media_worker.config import MediaConfig
    from media_worker.models import ConvertedMedia, MediaInfo
    from media_worker.service import create_app
    from mp3_bot.client import WorkerClient

    source = tmp_path / "worker-output.mp3"
    source.write_bytes(b"ID3 fixture")

    class Pipeline:
        async def info(self, url):
            return MediaInfo("Песня", "Автор", None)

        @asynccontextmanager
        async def convert(self, url):
            yield ConvertedMedia(source, MediaInfo("Песня", "Автор", duration), "Песня.mp3", 192)

        async def close(self):
            pass

    runner = web.AppRunner(create_app(MediaConfig(), pipeline=Pipeline()))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    try:
        async with aiohttp.ClientSession() as session:
            client = WorkerClient(settings(tmp_path, MEDIA_WORKER_URL=url), session)
            assert (await client.info(CANONICAL))["duration"] is None
            actual = await client.convert(CANONICAL, tmp_path / "bot-output.mp3")
            assert actual["duration"] == duration
            assert (tmp_path / "bot-output.mp3").read_bytes() == source.read_bytes()
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_telegram_rejection_is_labeled_upload_not_processing_error(tmp_path):
    from mp3_bot.app import BotRuntime

    session = TelegramSession()
    session.fail_audio = [
        lambda method: TelegramBadRequest(method=method, message="SECRET upload failure")
    ]
    bot = Bot(TOKEN, session=session)
    runtime = BotRuntime(settings(tmp_path), bot, FixtureWorker())
    await runtime.start()
    try:
        await runtime.dispatcher.feed_update(bot, update(URL))
        await asyncio.wait_for(runtime.queue.join(), 2)
        texts = [
            call.text for call in session.calls if isinstance(call, (SendMessage, EditMessageText))
        ]
        assert texts[-1] == "Could not send the MP3 to Telegram. Please try again later."
        assert not any("Could not process" in text for text in texts)
        assert not any("SECRET" in text for text in texts)
        assert not list(tmp_path.iterdir())
        assert len(session.audio_bytes) == 1
    finally:
        await runtime.close()


def test_known_worker_error_codes_use_the_shared_safe_messages(monkeypatch):
    from media_worker.errors import MESSAGES
    from mp3_bot.errors import public_message

    monkeypatch.setitem(MESSAGES, "new_worker_code", "A safe known error.")
    assert public_message("new_worker_code") == "A safe known error."
