"""One-shot HTTP worker client; MP3s never use shared filesystem paths."""

import base64
import binascii
import json
import math
import unicodedata
from contextlib import asynccontextmanager
from pathlib import Path

import aiohttp

from media_worker.errors import MediaError

from .config import Settings
from .errors import public_message


def metadata_from_payload(payload: object, *, audio: bool) -> dict:
    if not isinstance(payload, dict):
        raise MediaError("invalid_response")
    result = {}
    for key in ("title", "performer"):
        value = payload.get(key)
        if (
            not isinstance(value, str)
            or len(value) > 512
            or any(unicodedata.category(c).startswith("C") for c in value)
        ):
            raise MediaError("invalid_response")
        result[key] = value
    duration = payload.get("duration")
    if duration is None:
        pass  # Unknown duration is omitted at the Telegram upload boundary.
    elif (
        type(duration) not in (int, float)
        or not math.isfinite(duration)
        or not 0 <= duration <= 2147483647
    ):
        raise MediaError("invalid_response")
    result["duration"] = duration
    if audio:
        name = payload.get("filename")
        bitrate = payload.get("bitrate")
        if (
            not isinstance(name, str)
            or not name.endswith(".mp3")
            or len(name.encode("utf-8")) > 240
            or "/" in name
            or "\\" in name
            or any(unicodedata.category(c).startswith("C") for c in name)
            or type(bitrate) is not int
            or not 8 <= bitrate <= 320
        ):
            raise MediaError("invalid_response")
        result.update(filename=name, bitrate=bitrate)
    return result


async def bounded_json(response: aiohttp.ClientResponse) -> dict:
    data = bytearray()
    async for chunk in response.content.iter_chunked(8192):
        if len(data) + len(chunk) > 65536:
            raise MediaError("invalid_response")
        data.extend(chunk)
    try:
        payload = json.loads(data)
    except (ValueError, UnicodeError):
        raise MediaError("invalid_response") from None
    if not isinstance(payload, dict):
        raise MediaError("invalid_response")
    return payload


class WorkerClient:
    def __init__(self, settings: Settings, session: aiohttp.ClientSession):
        self.settings = settings
        self.session = session

    async def health(self) -> bool:
        try:
            async with self.session.get(
                self.settings.media_worker_url + "/health",
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                return response.status == 200
        except (aiohttp.ClientError, TimeoutError):
            return False

    async def _check_status(self, response: aiohttp.ClientResponse):
        if 200 <= response.status < 300:
            return
        payload = await bounded_json(response)
        code = payload.get("code")
        if not isinstance(code, str) or len(code) > 64:
            code = "worker_unavailable"
        raise MediaError(code, public_message(code))

    @asynccontextmanager
    async def _post(self, endpoint: str, url: str, total: int):
        try:
            async with self.session.post(
                self.settings.media_worker_url + endpoint,
                json={"url": url},
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=total, connect=min(15, total)),
            ) as response:
                yield response
        except TimeoutError:
            raise MediaError("worker_timeout", public_message("worker_timeout")) from None
        except aiohttp.ClientError:
            raise MediaError("worker_unavailable", public_message("worker_unavailable")) from None

    async def info(self, url: str) -> dict:
        async with self._post("/info", url, min(60, self.settings.download_timeout)) as response:
            await self._check_status(response)
            return metadata_from_payload(await bounded_json(response), audio=False)

    async def convert(self, url: str, path: Path) -> dict:
        total = self.settings.download_timeout + 4 * self.settings.conversion_timeout + 60
        async with self._post("/convert", url, total) as response:
            await self._check_status(response)
            encoded = response.headers.get("X-Media-Info", "")
            if not encoded or len(encoded) > 8192 or response.content_type != "audio/mpeg":
                raise MediaError("invalid_response")
            try:
                payload = json.loads(
                    base64.b64decode(
                        encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
                    )
                )
            except (ValueError, UnicodeError, binascii.Error):
                raise MediaError("invalid_response") from None
            metadata = metadata_from_payload(payload, audio=True)
            limit = self.settings.max_file_size_mb * 1_000_000
            if response.content_length is not None and response.content_length > limit:
                raise MediaError("file_too_large")
            size = 0
            with path.open("wb") as output:
                async for chunk in response.content.iter_chunked(65536):
                    size += len(chunk)
                    if size > limit:
                        raise MediaError("file_too_large")
                    output.write(chunk)
            if not size:
                raise MediaError("invalid_response")
            return metadata
