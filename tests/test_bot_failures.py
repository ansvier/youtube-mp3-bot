import asyncio

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter
from aiogram.methods import EditMessageText, SendAudio, SendMessage
from test_bot import TOKEN, URL, FixtureWorker, TelegramSession, settings, update


@pytest.mark.asyncio
async def test_status_fallback_sends_english_updates_when_initial_message_fails(tmp_path):
    from mp3_bot.app import BotRuntime

    class InitialStatusFailure(TelegramSession):
        async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109 - aiogram protocol
            if isinstance(method, SendMessage) and not self.calls:
                self.calls.append(method)
                raise TelegramNetworkError(method=method, message="synthetic status failure")
            return await super().make_request(bot, method, timeout)

    session = InitialStatusFailure()
    bot = Bot(TOKEN, session=session)
    runtime = BotRuntime(settings(tmp_path), bot, FixtureWorker())
    await runtime.start()
    try:
        await runtime.dispatcher.feed_update(bot, update(URL))
        await asyncio.wait_for(runtime.queue.join(), 2)
        assert [call.text for call in session.calls if isinstance(call, SendMessage)] == [
            "Getting video information…",
            "Downloading and converting to MP3…",
            "Sending the file…",
            "Done.",
        ]
        assert not any(isinstance(call, EditMessageText) for call in session.calls)
        assert len(session.audio_bytes) == 1
        assert not list(tmp_path.iterdir())
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_failed_status_edits_do_not_discard_audio(tmp_path):
    from mp3_bot.app import BotRuntime

    session = TelegramSession()
    session.fail_edits = True
    bot = Bot(TOKEN, session=session)
    runtime = BotRuntime(settings(tmp_path), bot, FixtureWorker())
    await runtime.start()
    try:
        await runtime.dispatcher.feed_update(bot, update(URL))
        await asyncio.wait_for(runtime.queue.join(), 2)
        assert len(session.audio_bytes) == 1
        assert not list(tmp_path.iterdir())
        assert all(not task.done() for task in runtime.tasks)
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_worker_failure_cleanup_and_queue_survives(tmp_path):
    from media_worker.errors import MediaError
    from mp3_bot.app import BotRuntime

    session = TelegramSession()
    bot = Bot(TOKEN, session=session)
    worker = FixtureWorker()
    worker.error = MediaError("file_too_large", "UNTRUSTED RAW PRIVATE URL")
    runtime = BotRuntime(settings(tmp_path, RATE_LIMIT_SECONDS="0"), bot, worker)
    await runtime.start()
    try:
        await runtime.dispatcher.feed_update(bot, update(URL))
        await asyncio.wait_for(runtime.queue.join(), 2)
        assert not list(tmp_path.iterdir())
        assert not session.audio_bytes
        texts = [
            call.text for call in session.calls if isinstance(call, (SendMessage, EditMessageText))
        ]
        assert texts[-1] == "The file exceeds the size limit. Please choose a shorter video."
        assert not any("UNTRUSTED" in text for text in texts)
        worker.error = None
        await runtime.dispatcher.feed_update(bot, update(URL))
        await asyncio.wait_for(runtime.queue.join(), 2)
        assert len(session.audio_bytes) == 1
    finally:
        await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_unknown_worker_failure_returns_safe_english_fallback(tmp_path, structured):
    from media_worker.errors import MediaError
    from mp3_bot.app import BotRuntime

    session = TelegramSession()
    bot = Bot(TOKEN, session=session)
    worker = FixtureWorker()
    raw = "UNTRUSTED RAW PRIVATE URL"
    worker.error = MediaError("new_worker_code", raw) if structured else RuntimeError(raw)
    runtime = BotRuntime(settings(tmp_path), bot, worker)
    await runtime.start()
    try:
        await runtime.dispatcher.feed_update(bot, update(URL))
        await asyncio.wait_for(runtime.queue.join(), 2)
        texts = [
            call.text for call in session.calls if isinstance(call, (SendMessage, EditMessageText))
        ]
        assert texts[-1] == "Could not process the video. Please try again later."
        assert not any(raw in text for text in texts)
        assert not session.audio_bytes
        assert not runtime.pending_users
        assert not list(tmp_path.iterdir())
        assert all(not task.done() for task in runtime.tasks)
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_ambiguous_upload_timeout_is_not_retried(tmp_path):
    from mp3_bot.app import BotRuntime

    session = TelegramSession()
    session.fail_audio = [
        lambda method: TelegramNetworkError(method=method, message="timeout with secret")
    ]
    bot = Bot(TOKEN, session=session)
    runtime = BotRuntime(settings(tmp_path), bot, FixtureWorker())
    await runtime.start()
    try:
        await runtime.dispatcher.feed_update(bot, update(URL))
        await asyncio.wait_for(runtime.queue.join(), 2)
        assert len(session.audio_bytes) == 1
        texts = [
            call.text for call in session.calls if isinstance(call, (SendMessage, EditMessageText))
        ]
        assert texts[-1] == (
            "Could not confirm delivery: the file may already have arrived. "
            "Please check the chat; I will not automatically send it again."
        )
        assert "Done." not in texts
        assert not list(tmp_path.iterdir())
    finally:
        await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("retry_after,failures,attempts", [(0, 1, 2), (0, 3, 3), (61, 1, 1)])
async def test_only_explicit_flood_control_retries_with_bounds(
    tmp_path, retry_after, failures, attempts
):
    from mp3_bot.app import BotRuntime

    session = TelegramSession()
    session.fail_audio = [
        lambda method: TelegramRetryAfter(method=method, message="flood", retry_after=retry_after)
    ] * failures
    bot = Bot(TOKEN, session=session)
    runtime = BotRuntime(settings(tmp_path), bot, FixtureWorker())
    await runtime.start()
    try:
        await runtime.dispatcher.feed_update(bot, update(URL))
        await asyncio.wait_for(runtime.queue.join(), 2)
        assert len([call for call in session.calls if isinstance(call, SendAudio)]) == attempts
        assert not list(tmp_path.iterdir())
        assert all(not task.done() for task in runtime.tasks)
    finally:
        await runtime.close()
