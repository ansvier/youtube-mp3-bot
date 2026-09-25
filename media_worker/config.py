"""Worker-only configuration; no token or bot configuration is loaded."""

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

BITRATES = (192, 128, 96, 64)


@dataclass(frozen=True)
class MediaConfig:
    max_concurrent: int = 1
    download_timeout: float = 600
    conversion_timeout: float = 300
    default_bitrate: int = 192
    max_file_bytes: int = 50_000_000
    max_source_bytes: int = 512_000_000
    temp_dir: Path = Path("/tmp/mp3-worker")
    cookies_file: Path | None = None
    local_api: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "MediaConfig":
        env = os.environ if env is None else env

        def positive(key, default, integer=False):
            raw = env.get(key, default)
            if key == "MAX_FILE_SIZE_MB" and raw == "":
                raw = default
            value = (int if integer else float)(raw)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{key} must be positive and finite")
            return value

        base = env.get("TELEGRAM_API_BASE_URL", "").strip()
        local = False
        if base:
            parsed = urlsplit(base)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
                or any(c.isspace() for c in base)
                or "\\" in base
            ):
                raise ValueError("Invalid TELEGRAM_API_BASE_URL")
            _ = parsed.port  # Validate malformed/out-of-range ports.
            local = parsed.hostname.lower().rstrip(".") != "api.telegram.org"
        file_mb = positive("MAX_FILE_SIZE_MB", 2000 if local else 50)
        if file_mb > (2000 if local else 50):
            raise ValueError("MAX_FILE_SIZE_MB exceeds API capacity")
        bitrate = positive("DEFAULT_AUDIO_BITRATE", 192, True)
        if bitrate not in BITRATES:
            raise ValueError("DEFAULT_AUDIO_BITRATE must be 192, 128, 96 or 64")
        cookies = Path(env["COOKIES_FILE"]) if env.get("COOKIES_FILE") else None
        if cookies is not None and (not cookies.is_file() or not os.access(cookies, os.R_OK)):
            raise ValueError("COOKIES_FILE must be a readable file")
        return cls(
            max_concurrent=positive("MAX_CONCURRENT_DOWNLOADS", 1, True),
            download_timeout=positive("DOWNLOAD_TIMEOUT", 600),
            conversion_timeout=positive("CONVERSION_TIMEOUT", 300),
            default_bitrate=bitrate,
            max_file_bytes=int(file_mb * 1_000_000),
            max_source_bytes=int(positive("MAX_SOURCE_SIZE_MB", 512) * 1_000_000),
            temp_dir=Path(env.get("TEMP_DIR", "/tmp/mp3-worker")),
            cookies_file=cookies,
            local_api=local,
        )
