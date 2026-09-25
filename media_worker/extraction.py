"""A deliberately narrow yt-dlp interface, inspired by MIT tg-media-bot.

Unlike upstream, no browser cookies, proxies, plugins or remote components.
All logs/errors remain private and raw diagnostics are never forwarded.
"""

import json
import math
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .config import MediaConfig
from .errors import MediaError
from .models import MediaInfo
from .process import run_process
from .urls import validate_url


def bounded_text(value, fallback="", max_bytes=512):
    if not isinstance(value, str):
        return fallback
    value = unicodedata.normalize("NFC", value)
    value = "".join(c for c in value if not unicodedata.category(c).startswith("C")).strip()
    return value.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore") or fallback


@dataclass(frozen=True)
class Extraction:
    info: MediaInfo
    thumbnail: str | None


class Extractor:
    def __init__(self, config: MediaConfig):
        self.config = config

    async def download(self, url: str, directory: Path, cookies: Path | None = None) -> Path:
        source = directory / "source.media"
        args = self._base(directory) + [
            "--output",
            str(source),
            "--max-filesize",
            str(self.config.max_source_bytes),
            "--match-filter",
            "!is_live",
            "--no-mtime",
        ]
        if cookies:
            args += ["--cookies", str(cookies)]
        await run_process(
            args + ["--", validate_url(url)],
            cwd=directory,
            timeout=self.config.download_timeout,
            output_limit=1_000_000,
            disk_limit=self.config.max_source_bytes + 8_000_000,
            error_code="download_failed",
        )
        if source.is_symlink() or not source.is_file() or source.stat().st_size == 0:
            raise MediaError("download_failed")
        if source.stat().st_size > self.config.max_source_bytes:
            raise MediaError("source_too_large")
        return source

    def _base(self, directory: Path):
        return [
            sys.executable,
            "-m",
            "yt_dlp",
            "--ignore-config",
            "--no-playlist",
            "--no-cache-dir",
            "--no-progress",
            "--no-remote-components",
            "--no-plugin-dirs",
            "--use-extractors",
            "Youtube",
            "--format",
            "bestaudio",
            "--downloader",
            "native",
            # Only the encoder may launch FFmpeg, with fixed local-file arguments.
            # yt-dlp sees a private directory containing no FFmpeg executables.
            "--ffmpeg-location",
            str(directory),
            "--socket-timeout",
            "30",
            "--retries",
            "2",
            "--fragment-retries",
            "2",
            "--abort-on-unavailable-fragments",
            "--concurrent-fragments",
            "1",
            "--fixup",
            "never",
        ]

    async def info(self, url: str, directory: Path, cookies: Path | None = None) -> Extraction:
        args = self._base(directory) + ["--dump-single-json", "--skip-download"]
        if cookies:
            args += ["--cookies", str(cookies)]
        result = await run_process(
            args + ["--", validate_url(url)],
            cwd=directory,
            timeout=self.config.download_timeout,
            output_limit=4_000_000,
            error_code="download_failed",
        )
        try:
            data = json.loads(result.stdout)
            if not isinstance(data, dict):
                raise ValueError
        except (ValueError, TypeError):
            raise MediaError("download_failed") from None
        if data.get("_type") in {"playlist", "multi_video"} or "entries" in data:
            raise MediaError("playlist")
        if data.get("is_live") or data.get("live_status") in {"is_live", "is_upcoming"}:
            raise MediaError("live")
        selections = [data] + (data.get("requested_downloads") or [])
        for item in selections:
            size = item.get("filesize") or item.get("filesize_approx")
            if isinstance(size, (int, float)) and size > self.config.max_source_bytes:
                raise MediaError("source_too_large")
        duration = data.get("duration")
        if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
            duration = None
        info = MediaInfo(
            bounded_text(data.get("title") or data.get("track"), "Audio"),
            bounded_text(
                data.get("artist") or data.get("uploader") or data.get("channel"), max_bytes=256
            ),
            duration,
        )
        thumbnail = data.get("thumbnail")
        return Extraction(info, thumbnail if isinstance(thumbnail, str) else None)
