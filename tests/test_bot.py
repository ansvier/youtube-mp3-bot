import asyncio
import importlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import EditMessageText, GetMe, SendAudio, SendMessage
from aiogram.types import Chat, Message, Update, User


class FixtureWorker:
    def __init__(self):
        self.calls = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.error: Exception | None = None

    async def info(self, url):
        self.calls.append(("info", url))
        return {"title": "Old info title", "performer": "Wrong artist", "duration": 999}

    async def convert(self, url, path):
        self.calls.append(("convert", url))
        path.write_bytes(b"ID3 fixture audio")
        self.started.set()
        await self.release.wait()
        if self.error:
            raise self.error
        return {
            "title": "Песня",
            "performer": "Автор",
            "duration": 12,
            "filename": "../Песня?.mp3",
            "bitrate": 192,
        }


TOKEN = "123456:" + "A" * 35
URL = "https://youtu.be/abcdefghijk"
CANONICAL = "https://www.youtube.com/watch?v=abcdefghijk"


class TelegramSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.audio_bytes = []
        self.audio_paths = []
        self.fail_audio = []
        self.fail_edits = False
        self.closed = False

    async def close(self):
        self.closed = True

    async def stream_content(self, *args, **kwargs):
        yield b""

    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109 - aiogram protocol
        self.calls.append(method)
        if isinstance(method, GetMe):
            return User(id=123456, is_bot=True, first_name="Private", username="private_test_bot")
        if isinstance(method, SendAudio):
            self.audio_paths.append(Path(method.audio.path))
            self.audio_bytes.append(b"".join([part async for part in method.audio.read(bot)]))
            if self.fail_audio:
                raise self.fail_audio.pop(0)(method)
        if isinstance(method, EditMessageText) and self.fail_edits:
            from aiogram.exceptions import TelegramBadRequest

            raise TelegramBadRequest(method=method, message="message cannot be edited")
        return Message(
            message_id=len(self.calls),
            date=datetime.now(UTC),
            chat=Chat(id=getattr(method, "chat_id", 10), type="private"),
            text=getattr(method, "text", None),
        )


def update(text="/start", user_id=10, chat_type="private", caption=None):
    return Update(
        update_id=1,
        message=Message(
            message_id=1,
            date=datetime.now(UTC),
            chat=Chat(id=user_id or 10, type=chat_type),
            from_user=User(id=user_id, is_bot=False, first_name="PRIVATE NAME")
            if user_id
            else None,
            text=text,
            caption=caption,
        ),
    )


def settings(tmp_path, **env):
    from mp3_bot.config import Settings

    return Settings.from_env(
        {"BOT_TOKEN": TOKEN, "ALLOWED_USER_IDS": "10,20,30,40", "TEMP_DIR": str(tmp_path), **env}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("user_id,chat_type", [(99, "private"), (10, "group"), (None, "private")])
async def test_authorization_gates_start_before_handlers(tmp_path, user_id, chat_type):
    app = importlib.import_module("mp3_bot.app")
    session = TelegramSession()
    bot = Bot(TOKEN, session=session)
    runtime = app.BotRuntime(settings(tmp_path), bot, worker=None)
    await runtime.dispatcher.feed_update(bot, update(user_id=user_id, chat_type=chat_type))
    assert not runtime.pending_users
    assert len(session.calls) == (1 if chat_type == "private" else 0)
    assert all(call.text == "Access denied. This is a private bot." for call in session.calls)
    await runtime.close()


@pytest.mark.asyncio
async def test_start_explains_automatic_audio_in_english(tmp_path):
    app = importlib.import_module("mp3_bot.app")
    session = TelegramSession()
    bot = Bot(TOKEN, session=session)
    runtime = app.BotRuntime(settings(tmp_path), bot, worker=None)
    await runtime.dispatcher.feed_update(bot, update())
    assert len(session.calls) == 1
    assert session.calls[0].text == (
        "Send a link to a single YouTube video and I will send you an MP3 audio file. "
        "I only process the first link in each message."
    )
    assert "/audio" not in session.calls[0].text
    await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("caption", [False, True])
async def test_url_automatically_sends_audio_with_actual_metadata_and_cleans(tmp_path, caption):
    from aiogram.types import FSInputFile

    from mp3_bot.app import BotRuntime

    session = TelegramSession()
    bot = Bot(TOKEN, session=session)
    worker = FixtureWorker()
    runtime = BotRuntime(settings(tmp_path), bot, worker)
    await runtime.start()
    try:
        text = URL + " " + "https://youtu.be/0123456789_"
        await runtime.dispatcher.feed_update(
            bot, update(text=None if caption else text, caption=text if caption else None)
        )
        await asyncio.wait_for(runtime.queue.join(), 2)
        audio = [call for call in session.calls if isinstance(call, SendAudio)]
        assert len(audio) == 1
        assert isinstance(audio[0].audio, FSInputFile)
        assert audio[0].title == "Песня"
        assert audio[0].performer == "Автор"
        assert audio[0].duration == 12
        assert audio[0].audio.filename == "Песня.mp3"
        assert session.audio_paths[0].name == "audio.mp3"
        assert session.audio_bytes == [b"ID3 fixture audio"]
        assert worker.calls == [("info", CANONICAL), ("convert", CANONICAL)]
        texts = [
            call.text for call in session.calls if isinstance(call, (SendMessage, EditMessageText))
        ]
        assert texts == [
            "Found multiple links; I will only process the first one.",
            "Getting video information…",
            "Downloading and converting to MP3…",
            "Sending the file…",
            "Done.",
        ]
        assert not list(tmp_path.iterdir())
        assert not runtime.pending_users
    finally:
        await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,expected",
    [
        ("hello", "Please send a valid YouTube video link."),
        ("https://evil.test/video", "Please send a valid YouTube video link."),
        (
            "https://youtube.com/playlist?list=xyz",
            "Please send a link to a single video, not a playlist.",
        ),
    ],
)
async def test_invalid_messages_receive_english_errors_without_worker_call(
    tmp_path, text, expected
):
    from mp3_bot.app import BotRuntime

    session = TelegramSession()
    bot = Bot(TOKEN, session=session)
    worker = FixtureWorker()
    runtime = BotRuntime(settings(tmp_path), bot, worker)
    await runtime.dispatcher.feed_update(bot, update(text))
    assert len(session.calls) == 1
    assert session.calls[0].text == expected
    assert not worker.calls
    await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason,expected",
    [
        ("stopping", "The bot is shutting down. Please try again later."),
        ("pending", "Your video is already queued or being processed."),
        ("rate", "Please wait a little before sending another link."),
        ("full", "The queue is full. Please try again later."),
    ],
)
async def test_admission_rejections_are_english_and_leave_queue_unchanged(
    tmp_path, reason, expected
):
    from mp3_bot.app import BotRuntime, Job

    session = TelegramSession()
    bot = Bot(TOKEN, session=session)
    worker = FixtureWorker()
    runtime = BotRuntime(settings(tmp_path, QUEUE_SIZE="1"), bot, worker, clock=lambda: 100.0)
    if reason == "stopping":
        runtime.stopping = True
    elif reason == "pending":
        runtime.pending_users.add(10)
    elif reason == "rate":
        runtime.last_accepted[10] = 99.0
    elif reason == "full":
        queued_message = update(URL, 20).message
        assert queued_message is not None
        runtime.queue.put_nowait(Job(queued_message, CANONICAL, 20))
        runtime.pending_users.add(20)
    pending = runtime.pending_users.copy()
    accepted = runtime.last_accepted.copy()
    queued = runtime.queue.qsize()
    try:
        await runtime.dispatcher.feed_update(bot, update(URL))
        assert len(session.calls) == 1
        assert session.calls[0].text == expected
        assert runtime.queue.qsize() == queued
        assert runtime.pending_users == pending
        assert runtime.last_accepted == accepted
        assert not worker.calls
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_queue_bounds_duplicate_rate_rejection_and_cancel_cleanup(tmp_path):
    from mp3_bot.app import BotRuntime

    session = TelegramSession()
    bot = Bot(TOKEN, session=session)
    worker = FixtureWorker()
    worker.release.clear()
    clock = [100.0]
    runtime = BotRuntime(settings(tmp_path, QUEUE_SIZE="1"), bot, worker, clock=lambda: clock[0])
    await runtime.start()
    try:
        await runtime.dispatcher.feed_update(bot, update(URL, 10))
        await asyncio.wait_for(worker.started.wait(), 2)
        await runtime.dispatcher.feed_update(bot, update(URL, 10))
        assert session.calls[-1].text == "Your video is already queued or being processed."
        await runtime.dispatcher.feed_update(bot, update(URL, 20))
        assert runtime.queue.qsize() == 1
        await runtime.dispatcher.feed_update(bot, update(URL, 30))
        assert session.calls[-1].text == "The queue is full. Please try again later."
        assert runtime.pending_users == {10, 20}
        worker.release.set()
        await asyncio.wait_for(runtime.queue.join(), 2)
        await runtime.dispatcher.feed_update(bot, update(URL, 10))
        assert session.calls[-1].text == "Please wait a little before sending another link."
        assert runtime.queue.empty()
        clock[0] += 31
        worker.started.clear()
        worker.release.clear()
        await runtime.dispatcher.feed_update(bot, update(URL, 10))
        await asyncio.wait_for(worker.started.wait(), 2)
        await runtime.dispatcher.feed_update(bot, update(URL, 20))
        await asyncio.wait_for(runtime.close(), 2)
        await asyncio.wait_for(runtime.queue.join(), 2)
        assert not list(tmp_path.iterdir())
        assert not runtime.pending_users
        assert not runtime.tasks
        await runtime.dispatcher.feed_update(bot, update(URL, 40))
        assert session.calls[-1].text == "The bot is shutting down. Please try again later."
    finally:
        await runtime.close()
