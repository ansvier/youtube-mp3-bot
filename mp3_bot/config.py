"""Explicit, import-safe configuration for the private bot."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    bot_token: str = field(repr=False)
    allowed_user_ids: frozenset[int]
    max_concurrent_downloads: int = 1
    download_timeout: int = 600
    conversion_timeout: int = 300
    default_audio_bitrate: int = 192
    max_file_size_mb: int = 50
    temp_dir: Path = Path("/tmp/mp3-bot")
    log_level: str = "INFO"
    cookies_file: str | None = field(default=None, repr=False)
    telegram_api_base_url: str | None = None
    media_worker_url: str = "http://worker:8080"
    rate_limit_seconds: int = 30
    queue_size: int = 5
    upload_timeout: int = 300

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        def invalid(key: str) -> ValueError:
            return ValueError(f"Invalid setting {key}")

        def number(key: str, default: int, minimum: int = 1, maximum: int = 86400) -> int:
            value = env.get(key, str(default))
            if key == "MAX_FILE_SIZE_MB" and value == "":
                value = str(default)
            if not re.fullmatch(r"[0-9]{1,12}", value):
                raise invalid(key)
            result = int(value)
            if not minimum <= result <= maximum:
                raise invalid(key)
            return result

        def base_url(key: str, default: str | None = None) -> str | None:
            value = env.get(key, default)
            if not value:
                return None
            try:
                parsed = urlsplit(value)
                valid = (
                    parsed.scheme in {"http", "https"}
                    and parsed.hostname
                    and parsed.username is None
                    and parsed.password is None
                    and not parsed.query
                    and not parsed.fragment
                    and not any(c.isspace() or ord(c) < 32 for c in value)
                    and "?" not in value
                    and "#" not in value
                    and (parsed.port is None or 1 <= parsed.port <= 65535)
                )
            except ValueError:
                valid = False
            if not valid:
                raise invalid(key)
            return value.rstrip("/")

        token = env.get("BOT_TOKEN", "")
        if not re.fullmatch(r"[1-9][0-9]{4,19}:[A-Za-z0-9_-]{35}", token):
            raise invalid("BOT_TOKEN")
        ids = env.get("ALLOWED_USER_IDS", "").split(",")
        if not all(
            re.fullmatch(r"[0-9]{1,19}", value.strip()) and int(value.strip()) > 0 for value in ids
        ):
            raise invalid("ALLOWED_USER_IDS")
        api = base_url("TELEGRAM_API_BASE_URL")
        custom = (
            api is not None and urlsplit(api).hostname.lower().rstrip(".") != "api.telegram.org"
        )
        limit = 2000 if custom else 50
        level = env.get("LOG_LEVEL", "INFO").upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise invalid("LOG_LEVEL")
        bitrate = number("DEFAULT_AUDIO_BITRATE", 192, maximum=320)
        if bitrate not in {64, 96, 128, 192}:
            raise invalid("DEFAULT_AUDIO_BITRATE")
        return cls(
            bot_token=token,
            allowed_user_ids=frozenset(int(value.strip()) for value in ids),
            max_concurrent_downloads=number("MAX_CONCURRENT_DOWNLOADS", 1, maximum=32),
            download_timeout=number("DOWNLOAD_TIMEOUT", 600),
            conversion_timeout=number("CONVERSION_TIMEOUT", 300),
            default_audio_bitrate=bitrate,
            max_file_size_mb=number("MAX_FILE_SIZE_MB", limit, maximum=limit),
            temp_dir=Path(env.get("TEMP_DIR", "/tmp/mp3-bot")),
            log_level=level,
            cookies_file=env.get("COOKIES_FILE") or None,
            telegram_api_base_url=api,
            media_worker_url=base_url("MEDIA_WORKER_URL", "http://worker:8080")
            or "http://worker:8080",
            rate_limit_seconds=number("RATE_LIMIT_SECONDS", 30, minimum=0),
            queue_size=number("QUEUE_SIZE", 5, maximum=1000),
            upload_timeout=number("UPLOAD_TIMEOUT", 300),
        )
