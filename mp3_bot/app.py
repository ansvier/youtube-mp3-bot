"""Private Telegram routing and bounded job orchestration."""

import asyncio
import logging
import math
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError, TelegramRetryAfter
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, Message, Update

from media_worker.errors import MediaError
from media_worker.naming import sanitize_filename
from media_worker.urls import extract_first

from .config import Settings
from .errors import public_message

log = logging.getLogger(__name__)


class PrivateAccess(BaseMiddleware):
    def __init__(self, allowed: frozenset[int]):
        self.allowed = allowed

    async def __call__(self, handler, event: Update, data):
        message = event.message
        sender = message.from_user if message else None
        if (
            not message
            or not sender
            or message.chat.type != "private"
            or sender.id not in self.allowed
        ):
            log.warning("Access denied user_id=%d", sender.id if sender else 0)
            if message and message.chat.type == "private":
                try:
                    await message.answer(
                        "Access denied. This is a private bot.", request_timeout=15
                    )
                except Exception:
                    log.exception("Denial delivery failed")
            return None
        return await handler(event, data)


@dataclass
class Job:
    message: Message
    url: str
    user_id: int


class BotRuntime:
    def __init__(self, settings: Settings, bot: Bot, worker, *, clock=time.monotonic):
        self.settings = settings
        self.bot = bot
        self.worker = worker
        self.clock = clock
        self.last_accepted: dict[int, float] = {}
        self.stopping = False
        self.pending_users: set[int] = set()
        self.queue: asyncio.Queue[Job] = asyncio.Queue(maxsize=settings.queue_size)
        self.tasks: list[asyncio.Task] = []
        self.dispatcher = Dispatcher(disable_fsm=True)
        self.dispatcher.update.outer_middleware(PrivateAccess(settings.allowed_user_ids))
        self.dispatcher.message.register(self.on_start, CommandStart())
        self.dispatcher.message.register(self.on_message)

    async def on_start(self, message: Message):
        await message.answer(
            "Send a link to a single YouTube video and I will send you an MP3 audio file. "
            "I only process the first link in each message.",
            request_timeout=15,
        )

    async def on_message(self, message: Message):
        try:
            extracted = extract_first(message.text or message.caption or "")
        except MediaError as error:
            await message.answer(public_message(error.code), request_timeout=15)
            return
        user_id = message.from_user.id
        now = self.clock()
        reason = None
        if self.stopping:
            reason = "The bot is shutting down. Please try again later."
        elif user_id in self.pending_users:
            reason = "Your video is already queued or being processed."
        elif (
            now - self.last_accepted.get(user_id, float("-inf")) < self.settings.rate_limit_seconds
        ):
            reason = "Please wait a little before sending another link."
        elif self.queue.full():
            reason = "The queue is full. Please try again later."
        if reason:
            await message.answer(reason, request_timeout=15)
            return
        # Admission is atomic: no await between checks and queue insertion.
        self.pending_users.add(user_id)
        self.last_accepted[user_id] = now
        self.queue.put_nowait(Job(message, extracted.url, user_id))
        if extracted.count > 1:
            await message.answer(
                "Found multiple links; I will only process the first one.", request_timeout=15
            )

    async def start(self):
        self.settings.temp_dir.mkdir(parents=True, exist_ok=True)
        self.tasks = [
            asyncio.create_task(self._consume())
            for _ in range(self.settings.max_concurrent_downloads)
        ]

    async def _consume(self):
        while True:
            job = await self.queue.get()
            try:
                await self._process(job)
            except Exception as error:
                log.exception("Job failed user_id=%d", job.user_id)
                await self._answer(
                    job.message,
                    public_message(error.code)
                    if isinstance(error, MediaError)
                    else public_message("unknown"),
                )
            finally:
                self.pending_users.discard(job.user_id)
                self.queue.task_done()

    async def _process(self, job: Job):
        with tempfile.TemporaryDirectory(prefix="job-", dir=self.settings.temp_dir) as directory:
            path = Path(directory) / "audio.mp3"
            status = await self._answer(job.message, "Getting video information…")
            await self.worker.info(job.url)
            await self._status(job.message, status, "Downloading and converting to MP3…")
            metadata = await self.worker.convert(job.url, path)
            await self._status(job.message, status, "Sending the file…")
            try:
                await self._upload(job, path, metadata)
            except (TelegramNetworkError, TimeoutError):
                log.exception("Upload delivery uncertain user_id=%d", job.user_id)
                await self._answer(
                    job.message,
                    "Could not confirm delivery: the file may already have arrived. "
                    "Please check the chat; I will not automatically send it again.",
                )
                return
            except TelegramAPIError:
                log.exception("Upload rejected user_id=%d", job.user_id)
                await self._answer(job.message, public_message("upload_failed"))
                return
            await self._status(job.message, status, "Done.")

    async def _answer(self, message: Message, text: str):
        try:
            async with asyncio.timeout(15):
                return await message.answer(text, request_timeout=15)
        except Exception:
            log.exception("Status delivery failed")
            return None

    async def _status(self, message: Message, status: Message | None, text: str):
        if status is None:
            await self._answer(message, text)
            return
        try:
            async with asyncio.timeout(15):
                await self.bot.edit_message_text(
                    text, chat_id=message.chat.id, message_id=status.message_id, request_timeout=15
                )
        except Exception:
            log.exception("Status edit failed")

    async def _upload(self, job: Job, path: Path, metadata: dict):
        # MIT upstream's sendAudio/flood-control pattern, with stricter bounds.
        # Retry ONLY explicit 429, never ambiguous transport failures.
        for attempt in range(3):
            try:
                async with asyncio.timeout(self.settings.upload_timeout):
                    return await self.bot.send_audio(
                        job.message.chat.id,
                        FSInputFile(path, filename=sanitize_filename(metadata["filename"])),
                        title=metadata["title"],
                        performer=metadata["performer"],
                        duration=math.ceil(metadata["duration"])
                        if metadata.get("duration") is not None
                        else None,
                        request_timeout=self.settings.upload_timeout,
                    )
            except TelegramRetryAfter as error:
                if attempt >= 2 or not 0 <= error.retry_after <= 60:
                    raise
                await asyncio.sleep(error.retry_after)

    async def close(self):
        self.stopping = True
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        while not self.queue.empty():
            job = self.queue.get_nowait()
            self.pending_users.discard(job.user_id)
            self.queue.task_done()
