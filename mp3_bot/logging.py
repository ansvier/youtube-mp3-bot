"""Diagnostic tracebacks without Telegram credentials or media URLs."""

import logging
import re
import sys
from collections.abc import Iterable
from typing import TextIO


class RedactingFormatter(logging.Formatter):
    def __init__(self, secrets: Iterable[str] = ()):
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")
        self.secrets = tuple(value for value in secrets if value)

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for value in self.secrets:
            text = text.replace(value, "[REDACTED]")
        text = re.sub(r"\b[0-9]{5,20}:[A-Za-z0-9_-]{20,}\b", "[REDACTED]", text)
        text = re.sub(r"https?://[^\s\"'<>]+", "[REDACTED]", text, flags=re.I)
        text = re.sub(r"(?im)(cookie(?:s)?|authorization)\s*[:=][^\n]*", r"\1: [REDACTED]", text)
        text = re.sub(r"(?m)^.*\t(?:TRUE|FALSE)\t.*$", "[REDACTED]", text)
        return text


def configure_logging(
    level: str, *, secrets: Iterable[str] = (), stream: TextIO | None = None
) -> None:
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(RedactingFormatter(secrets))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    # These libraries log update objects and token-bearing URLs, even at INFO.
    # Suppress at the namespace boundary regardless of the application log level.
    for name in ("aiogram", "aiohttp"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        logger.setLevel(logging.CRITICAL + 1)
