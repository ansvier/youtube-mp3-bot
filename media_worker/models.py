"""Small worker domain records."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MediaInfo:
    title: str
    performer: str
    duration: float | None


@dataclass(frozen=True)
class ConvertedMedia:
    path: Path
    info: MediaInfo
    filename: str
    bitrate: int
