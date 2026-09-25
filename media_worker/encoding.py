"""Encode local audio, then tag, then measure the complete MP3.

The upstream MIT tg-media-bot informed cover-as-album-art and byte-safe
filenames; conversion and isolation are implemented independently here.
"""

import json
import math
import shutil
from dataclasses import replace
from pathlib import Path

from mutagen.id3 import APIC, ID3, TIT2, TPE1

from .config import BITRATES, MediaConfig
from .errors import MediaError
from .models import ConvertedMedia, MediaInfo
from .naming import sanitize_filename
from .process import run_process

LOCAL_FORMATS = "mov,matroska,webm,ogg,mp3,wav,flac,aac,mpegts"
MAX_COVER_BYTES = 2_000_000


async def probe_duration(path: Path, timeout: float) -> float:  # noqa: ASYNC109 - delegated process deadline
    result = await run_process(
        [
            "ffprobe",
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-format_whitelist",
            LOCAL_FORMATS,
            "-threads",
            "1",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        cwd=path.parent,
        timeout=timeout,
        output_limit=8192,
    )
    try:
        duration = float(json.loads(result.stdout)["format"]["duration"])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError
        return duration
    except (KeyError, ValueError, TypeError):
        raise MediaError("processing_failed") from None


def cover_mime(cover: bytes | None) -> str | None:
    if not cover or len(cover) > MAX_COVER_BYTES:
        return None
    if cover.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if cover.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return None


async def encode_source(
    source: Path,
    info: MediaInfo,
    config: MediaConfig,
    *,
    cover: bytes | None = None,
) -> ConvertedMedia:
    source = source.resolve(strict=True)  # noqa: ASYNC240 - local per-job path
    duration = await probe_duration(source, config.conversion_timeout)
    output = source.parent / "audio.mp3"
    bitrates = (
        (config.default_bitrate,)
        if config.local_api
        else tuple(bitrate for bitrate in BITRATES if bitrate <= config.default_bitrate)
    )
    for bitrate in bitrates:
        await run_process(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-protocol_whitelist",
                "file,pipe",
                "-format_whitelist",
                LOCAL_FORMATS,
                "-threads",
                "1",
                "-i",
                str(source),
                "-t",
                str(duration + 1),
                "-map",
                "0:a:0",
                "-vn",
                "-sn",
                "-dn",
                "-map_metadata",
                "-1",
                "-c:a",
                "libmp3lame",
                "-ar",
                "44100",
                "-b:a",
                f"{bitrate}k",
                "-threads",
                "1",
                "-fs",
                str(config.max_file_bytes + 2_000_000),
                str(output),
            ],
            cwd=source.parent,
            timeout=config.conversion_timeout,
            disk_limit=config.max_source_bytes + config.max_file_bytes + 8_000_000,
        )
        tags = ID3(output)
        tags.add(TIT2(encoding=3, text=info.title))
        tags.add(TPE1(encoding=3, text=info.performer))
        tags.save(output, v2_version=3, padding=lambda _: 0)
        mime = cover_mime(cover)
        if mime:
            await _embed_cover_best_effort(output, cover, mime, config.conversion_timeout)
        if output.stat().st_size <= config.max_file_bytes:
            actual_duration = await probe_duration(output, config.conversion_timeout)
            if actual_duration < duration - 0.1:
                raise MediaError("processing_failed")
            return ConvertedMedia(
                output,
                replace(info, duration=actual_duration),
                sanitize_filename(info.title),
                bitrate,
            )
        output.unlink()
    if config.local_api:
        raise MediaError("too_large", "The MP3 exceeds the configured local API size limit.")
    raise MediaError("too_large")


async def _embed_cover_best_effort(output, cover, mime, deadline):
    # Mutagen may partially write before failing: never risk the clean audio.
    candidate = output.with_name("covered.mp3")
    try:
        shutil.copyfile(output, candidate)
        tags = ID3(candidate)
        tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=cover))
        tags.save(candidate, v2_version=3, padding=lambda _: 0)
        await probe_duration(candidate, deadline)
        candidate.replace(output)
    except Exception:
        pass  # Optional cover failure cannot invalidate the already-tagged MP3.
    finally:
        candidate.unlink(missing_ok=True)
