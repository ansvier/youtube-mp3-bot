"""Explicit bot configuration, lifecycle and network-free diagnostics."""

import argparse
import asyncio
import logging
import os
from pathlib import Path

import aiohttp
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from dotenv import load_dotenv

from .app import BotRuntime
from .client import WorkerClient  # Import verifies bot-side dependencies only.
from .config import Settings
from .health import HealthMarker
from .logging import configure_logging


def create_bot(settings: Settings) -> Bot:
    kwargs = {"timeout": settings.upload_timeout}
    if settings.telegram_api_base_url:
        kwargs["api"] = TelegramAPIServer.from_base(settings.telegram_api_base_url, is_local=False)
    return Bot(settings.bot_token, session=AiohttpSession(**kwargs))


async def run(settings: Settings) -> None:
    marker = HealthMarker(settings.temp_dir)
    marker.clear()
    bot = create_bot(settings)
    bot.session.middleware(marker.observe_polling)
    heartbeat = None
    async with aiohttp.ClientSession(trust_env=False) as session:
        worker = WorkerClient(settings, session)
        runtime = BotRuntime(settings, bot, worker)

        async def ready(**kwargs):
            nonlocal heartbeat
            await runtime.start()
            heartbeat = asyncio.create_task(marker.run(worker), name="bot-heartbeat")

        runtime.dispatcher.startup.register(ready)
        try:
            # Auth must succeed before polling startup can create a heartbeat.
            async with asyncio.timeout(15):
                await bot.me()
            await runtime.dispatcher.start_polling(
                bot,
                handle_signals=True,
                close_bot_session=False,
                handle_as_tasks=False,
                polling_timeout=10,
                allowed_updates=["message"],
            )
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
            marker.clear()
            try:
                async with asyncio.timeout(20):
                    await runtime.close()
            finally:
                async with asyncio.timeout(5):
                    await bot.session.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Private YouTube to MP3 bot")
    parser.add_argument(
        "--check", action="store_true", help="Check configuration without network access"
    )
    parser.add_argument("--healthcheck", action="store_true", help="Check the process heartbeat")
    args = parser.parse_args(argv)
    load_dotenv(Path.cwd() / ".env", override=False)
    if args.healthcheck:
        return (
            0 if HealthMarker(Path(os.environ.get("TEMP_DIR", "/tmp/mp3-bot"))).is_healthy() else 1
        )
    configure_logging("INFO", secrets=(os.environ.get("BOT_TOKEN", ""),))
    try:
        settings = Settings.from_env(os.environ)
    except ValueError as error:
        logging.getLogger(__name__).error("%s", error)
        return 1
    configure_logging(settings.log_level, secrets=(settings.bot_token,))
    if args.check:
        print("Bot configuration and dependencies verified.")
        return 0
    try:
        asyncio.run(run(settings))
    except KeyboardInterrupt:
        return 0
    except Exception:
        logging.getLogger(__name__).exception("Bot stopped with an error")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
