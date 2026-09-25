"""Optional, capped cover retrieval from YouTube's image hosts only."""

import re
from urllib.parse import urlsplit

import aiohttp

from .encoding import MAX_COVER_BYTES, cover_mime


async def fetch_cover(url: str | None) -> bytes | None:
    if not isinstance(url, str) or len(url) > 2048 or re.search(r"[\s\\\x00-\x1f]", url):
        return None
    try:
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or parts.netloc not in {"i.ytimg.com", "img.youtube.com"}
            or not re.fullmatch(r"/vi/[A-Za-z0-9_-]{11}/[A-Za-z0-9_-]+\.(?:jpg|png)", parts.path)
        ):
            return None
        async with aiohttp.ClientSession(
            trust_env=False,
            timeout=aiohttp.ClientTimeout(total=10),
            auto_decompress=False,
        ) as session:
            async with session.get(url, allow_redirects=False) as response:
                if response.status != 200 or (response.content_length or 0) > MAX_COVER_BYTES:
                    return None
                data = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    if len(data) + len(chunk) > MAX_COVER_BYTES:
                        return None
                    data.extend(chunk)
                result = bytes(data)
                return result if cover_mime(result) else None
    except (aiohttp.ClientError, TimeoutError, OSError, ValueError):
        return None
