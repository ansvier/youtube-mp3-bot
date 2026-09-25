"""Argument-array subprocesses with an explicit non-secret environment."""

import asyncio
import logging
import os
import signal
from dataclasses import dataclass
from pathlib import Path

from .diagnostics import safe_traceback, scrub_diagnostics
from .errors import MediaError, classify_download_error

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessResult:
    stdout: bytes
    stderr: bytes
    returncode: int


def child_environment(cwd: Path) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(cwd),
        "TMPDIR": str(cwd),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONUTF8": "1",
    }


async def run_process(
    args: list[str],
    *,
    cwd: Path,
    timeout: float,  # noqa: ASYNC109 - owns group termination
    output_limit: int = 4_000_000,
    disk_limit: int | None = None,
    error_code: str = "processing_failed",
) -> ProcessResult:
    # Shield the OS-spawn handoff: cancellation must not lose the process handle.
    creation = asyncio.create_task(
        asyncio.create_subprocess_exec(
            *args,
            cwd=cwd,
            env=child_environment(cwd),
            start_new_session=True,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    )
    process, cancelled = await _join_despite_cancellation(creation)
    if cancelled:
        await _join_despite_cancellation(asyncio.create_task(_terminate_group(process)))
        raise asyncio.CancelledError
    readers = [
        asyncio.create_task(_read_bounded(stream, output_limit))
        for stream in (process.stdout, process.stderr)
    ]
    watchdog = asyncio.create_task(_watch_disk(cwd, disk_limit))
    communication = asyncio.gather(*readers, process.wait())
    try:
        async with asyncio.timeout(timeout):
            done, _ = await asyncio.wait(
                {communication, watchdog}, return_when=asyncio.FIRST_COMPLETED
            )
            if watchdog in done:
                watchdog.result()
            stdout, stderr, _ = await communication
            _check_disk(cwd, disk_limit)
        if process.returncode:
            logger.error(
                "media_process_failed stage=%s exit=%s exception=MediaError traceback=%s stderr=%s",
                error_code,
                process.returncode,
                safe_traceback(),
                scrub_diagnostics(stderr.decode("utf-8", errors="replace")),
            )
            code = (
                classify_download_error(stderr) if error_code == "download_failed" else error_code
            )
            raise MediaError(code)
        return ProcessResult(stdout, stderr, process.returncode)
    except TimeoutError:
        raise MediaError("timeout") from None
    finally:
        cleanup = asyncio.create_task(_finish(process, watchdog, communication, readers))
        _, cancelled = await _join_despite_cancellation(cleanup)
        if cancelled:
            raise asyncio.CancelledError


async def _join_despite_cancellation(task):
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    return task.result(), cancelled


async def _finish(process, watchdog, communication, readers):
    await _terminate_group(process)
    for task in (watchdog, communication, *readers):
        task.cancel()
    await asyncio.gather(watchdog, communication, *readers, return_exceptions=True)


async def _read_bounded(stream, limit):
    chunks = bytearray()
    while chunk := await stream.read(65536):
        if len(chunks) + len(chunk) > limit:
            raise MediaError("process_output")
        chunks.extend(chunk)
    return bytes(chunks)


def _check_disk(cwd, limit):
    if limit is None:
        return
    size = 0
    for path in cwd.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                size += path.stat().st_size
        except FileNotFoundError:
            continue
        if size > limit:
            raise MediaError("source_too_large")


async def _watch_disk(cwd, limit):
    while True:
        _check_disk(cwd, limit)
        await asyncio.sleep(0.05)


async def _terminate_group(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=0.5)
    except TimeoutError:
        pass
    # A leader can exit while a grandchild still holds the inherited pipes.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await process.wait()
