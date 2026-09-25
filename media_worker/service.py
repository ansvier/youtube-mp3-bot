"""Internal HTTP contract. Bind only on the worker's private network."""

import asyncio
import base64
import json
import logging
from dataclasses import asdict

from aiohttp import web

from .config import MediaConfig
from .diagnostics import safe_traceback
from .errors import MediaError
from .pipeline import MediaPipeline
from .urls import validate_url

logger = logging.getLogger(__name__)


@web.middleware
async def safe_errors(request, handler):
    try:
        return await handler(request)
    except MediaError as error:
        pass_error = error
    except (web.HTTPException, ValueError, TypeError):
        pass_error = MediaError("invalid_request")
    except Exception as error:
        # No user text, URLs, cookies, paths, stderr, or credentials in logs.
        logger.error(
            "worker_failure stage=request exception=%s traceback=%s",
            type(error).__name__,
            safe_traceback(error.__traceback__),
        )
        pass_error = MediaError("processing_failed")
    return web.json_response({"code": pass_error.code, "message": pass_error.message}, status=400)


async def _read_url(request):
    if request.query or request.content_type != "application/json":
        raise MediaError("invalid_request")
    data = await request.json()
    if not isinstance(data, dict) or set(data) != {"url"}:
        raise MediaError("invalid_request")
    return validate_url(data["url"])


def create_app(config: MediaConfig | None = None, *, pipeline=None) -> web.Application:
    config = config or MediaConfig.from_env()
    pipeline = pipeline or MediaPipeline(config)
    app = web.Application(client_max_size=4096, middlewares=[safe_errors])

    async def health(request):
        return web.json_response({"status": "ok"})

    async def info(request):
        result = await pipeline.info(await _read_url(request))
        return web.json_response(asdict(result), dumps=_json)

    async def convert(request):
        url = await _read_url(request)
        async with pipeline.convert(url) as result:
            data = asdict(result.info) | {"filename": result.filename, "bitrate": result.bitrate}
            header = base64.urlsafe_b64encode(_json(data).encode("utf-8")).decode("ascii")
            if len(header) >= 4096:
                raise MediaError("processing_failed")
            response = web.StreamResponse(
                headers={
                    "Content-Type": "audio/mpeg",
                    "Content-Length": str(result.path.stat().st_size),
                    "X-Media-Info": header,
                    "Cache-Control": "no-store",
                }
            )
            await response.prepare(request)
            try:
                async with asyncio.timeout(300):
                    with result.path.open("rb") as stream:
                        while chunk := stream.read(65536):
                            await response.write(chunk)
                    await response.write_eof()
            except Exception:
                # A prepared audio response must never acquire a JSON error tail.
                if request.transport:
                    request.transport.close()
            return response

    async def shutdown(app):
        await pipeline.close()

    app.router.add_get("/health", health)
    app.router.add_post("/info", info)
    app.router.add_post("/convert", convert)
    app.on_shutdown.append(shutdown)
    return app


def _json(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
