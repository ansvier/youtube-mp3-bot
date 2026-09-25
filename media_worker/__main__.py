"""Worker command-line entry point; diagnostics never include raw failures."""

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

import aiohttp
from aiohttp import web

from .config import MediaConfig
from .errors import MediaError
from .process import run_process
from .service import create_app


async def check(config):
    config.temp_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="check-", dir=config.temp_dir) as name:
        directory = Path(name).resolve()  # noqa: ASYNC240 - local tmpfs, no detached I/O
        tools = [
            [sys.executable, "-m", "yt_dlp", "--ignore-config", "--version"],
            ["ffmpeg", "-version"],
            ["ffprobe", "-version"],
            ["deno", "--version"],
        ]
        for command in tools:
            await run_process(command, cwd=directory, timeout=10)
        encoders = await run_process(
            ["ffmpeg", "-hide_banner", "-encoders"], cwd=directory, timeout=10
        )
        if b"libmp3lame" not in encoders.stdout:
            raise MediaError("dependency_failed")
    return {"status": "ok", "tools": ["yt-dlp", "ffmpeg", "ffprobe", "deno"]}


async def healthcheck():
    try:
        async with aiohttp.ClientSession(
            trust_env=False, timeout=aiohttp.ClientTimeout(total=2)
        ) as client:
            async with client.get(
                "http://127.0.0.1:8080/health", allow_redirects=False
            ) as response:
                return response.status == 200 and await response.json() == {"status": "ok"}
    except (aiohttp.ClientError, OSError, TimeoutError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description="Internal isolated MP3 worker")
    parser.add_argument(
        "--check", action="store_true", help="Validate settings and local tools, no network"
    )
    parser.add_argument(
        "--healthcheck", action="store_true", help="Check the local worker HTTP endpoint"
    )
    args = parser.parse_args()
    try:
        if args.healthcheck:
            return 0 if asyncio.run(healthcheck()) else 1
        config = MediaConfig.from_env()
        if args.check:
            print(json.dumps(asyncio.run(check(config))))
        else:
            web.run_app(
                create_app(config),
                host="0.0.0.0",
                port=8080,
                handler_cancellation=True,
                access_log=None,
                print=None,
                shutdown_timeout=10,
            )
        return 0
    except (MediaError, ValueError, OSError):
        print("Worker configuration or dependency check failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
