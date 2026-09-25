"""Strict YouTube URL canonicalization; no network or startup side effects."""

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from .errors import MediaError

HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
        "www.youtu.be",
    }
)
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
URL_IN_TEXT = re.compile(
    r"(?<![\w@.-])(?:[a-z][a-z0-9+.-]*://[^\s<>]*|"
    r"(?:(?:www|m|music)\.)?(?:youtube\.com|youtu\.be)/[^\s<>]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExtractedURL:
    url: str
    count: int


def extract_first(text: str) -> ExtractedURL:
    matches = list(URL_IN_TEXT.finditer(text))
    if not matches:
        raise MediaError("invalid_url")
    first = matches[0].group().rstrip(".,;:!?)]}»\"'")
    if "://" not in first:
        first = "https://" + first
    return ExtractedURL(validate_url(first), len(matches))


def validate_url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 2048 or re.search(r"[\s\\\x00-\x1f\x7f]", url):
        raise MediaError("invalid_url")
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or parts.netloc.lower() not in HOSTS:
            raise MediaError("invalid_url")
        query = parse_qs(parts.query, keep_blank_values=True, max_num_fields=64)
        if parts.path == "/playlist" or (
            parts.path == "/watch" and "v" not in query and "list" in query
        ):
            raise MediaError("playlist")
        if parts.netloc.lower() in {"youtu.be", "www.youtu.be"}:
            video_id = parts.path[1:]
        elif parts.path == "/watch":
            ids = query.get("v", [])
            raw_ids = [part[2:] for part in parts.query.split("&") if part.startswith("v=")]
            video_id = raw_ids[0] if len(ids) == len(raw_ids) == 1 else ""
        else:
            match = re.fullmatch(r"/(shorts|embed|live)/([A-Za-z0-9_-]{11})", parts.path)
            video_id = match[2] if match else ""
        if not VIDEO_ID.fullmatch(video_id):
            raise MediaError("invalid_url")
    except ValueError:
        raise MediaError("invalid_url") from None
    return f"https://www.youtube.com/watch?v={video_id}"
