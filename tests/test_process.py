import asyncio
import json
import os
import signal
import sys
import time

import pytest


@pytest.mark.asyncio
async def test_child_is_argv_only_and_receives_no_ambient_credentials(tmp_path, monkeypatch):
    from media_worker.process import run_process

    monkeypatch.setenv("BOT_TOKEN", "must-not-leak")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-leak")
    monkeypatch.setenv("HTTP_PROXY", "http://credential.example")
    result = await run_process(
        [
            sys.executable,
            "-c",
            "import os,json,sys; print(json.dumps(dict(os.environ))); print(sys.argv[1])",
            ";touch SHOULD_NOT_EXIST",
        ],
        cwd=tmp_path,
        timeout=5,
    )
    env = json.loads(result.stdout.splitlines()[0])
    assert not {"BOT_TOKEN", "AWS_SECRET_ACCESS_KEY", "HTTP_PROXY"} & env.keys()
    assert env["HOME"] == str(tmp_path)
    assert result.stdout.splitlines()[1] == b";touch SHOULD_NOT_EXIST"
    assert not (tmp_path / "SHOULD_NOT_EXIST").exists()


TREE_SCRIPT = """
import os, subprocess, sys, signal
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(2)'])
def stop(*args):
    child.wait()
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
Path('pids').write_text(f'{os.getpid()} {child.pid}')
child.wait()
"""


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_timeout_or_cancel_joins_entire_process_group(tmp_path, cancel):
    from media_worker.errors import MediaError
    from media_worker.process import run_process

    task = asyncio.create_task(
        run_process(
            [sys.executable, "-c", TREE_SCRIPT],
            cwd=tmp_path,
            timeout=0.3,
        )
    )
    for _ in range(200):
        if (tmp_path / "pids").exists():
            break
        await asyncio.sleep(0.01)
    pids = [int(x) for x in (tmp_path / "pids").read_text().split()]
    start = time.monotonic()
    try:
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(MediaError) as error:
                await task
            assert error.value.code == "timeout"
        assert time.monotonic() - start < 1.5
        for pid in pids:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
    finally:
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["stdout", "stderr", "disk"])
async def test_process_resource_watchdogs(tmp_path, mode):
    from media_worker.errors import MediaError
    from media_worker.process import run_process

    script = {
        "stdout": 'print("x" * 100000)',
        "stderr": 'import sys; sys.stderr.write("x" * 100000)',
        "disk": 'from pathlib import Path; import time; Path("source.part").write_bytes(b"x" * 100000); time.sleep(2)',
    }[mode]
    with pytest.raises(MediaError) as error:
        await run_process(
            [sys.executable, "-c", script],
            cwd=tmp_path,
            timeout=3,
            output_limit=1024,
            disk_limit=1024,
        )
    assert error.value.code == ("source_too_large" if mode == "disk" else "process_output")


@pytest.mark.asyncio
async def test_nonzero_process_exit_maps_to_safe_error(tmp_path):
    from media_worker.errors import MediaError
    from media_worker.process import run_process

    with pytest.raises(MediaError) as error:
        await run_process(
            [sys.executable, "-c", 'import sys; sys.stderr.write("SECRET"); sys.exit(4)'],
            cwd=tmp_path,
            timeout=3,
        )
    assert error.value.code == "processing_failed"
    assert "SECRET" not in str(error.value)


@pytest.mark.asyncio
async def test_cancellation_during_cleanup_is_not_swallowed(tmp_path, monkeypatch):
    from media_worker import process

    entered = asyncio.Event()
    release = asyncio.Event()
    original = process._terminate_group

    async def delayed_cleanup(child):
        entered.set()
        await release.wait()
        await original(child)

    monkeypatch.setattr(process, "_terminate_group", delayed_cleanup)
    task = asyncio.create_task(
        process.run_process([sys.executable, "-c", "pass"], cwd=tmp_path, timeout=3)
    )
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_cancellation_during_spawn_still_joins_child(tmp_path, monkeypatch):
    from media_worker import process

    entered = asyncio.Event()
    release = asyncio.Event()
    children = []
    original = process.asyncio.create_subprocess_exec

    async def delayed_spawn(*args, **kwargs):
        child = await original(*args, **kwargs)
        children.append(child)
        entered.set()
        await release.wait()
        return child

    monkeypatch.setattr(process.asyncio, "create_subprocess_exec", delayed_spawn)
    task = asyncio.create_task(
        process.run_process(
            [sys.executable, "-c", "import time; time.sleep(2)"], cwd=tmp_path, timeout=3
        )
    )
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    release.set()
    try:
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ProcessLookupError):
            os.kill(children[0].pid, 0)
    finally:
        for child in children:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await child.wait()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "diagnostic,code",
    [
        ("ERROR: Private video. Sign in if you have access", "private"),
        ("ERROR: Video unavailable. This video has been removed", "unavailable"),
        ("ERROR: Sign in to confirm your age", "age_restricted"),
        (
            "ERROR: The uploader has not made this video available in your country",
            "region_restricted",
        ),
        ("ERROR: Sign in to confirm you're not a bot. Use --cookies", "cookies_required"),
    ],
)
async def test_download_failure_classification_and_scrubbed_diagnostics(
    tmp_path, caplog, diagnostic, code
):
    from media_worker.errors import MediaError
    from media_worker.process import run_process

    stderr = (
        diagnostic
        + "\nrequest https://video.example/download?sig=never-log-this\nCookie: SID=cookie-private-value\n/private/cookie-file.txt"
    )
    script = "import sys; sys.stderr.write(" + repr(stderr) + "); sys.exit(1)"
    with pytest.raises(MediaError) as error:
        await run_process(
            [sys.executable, "-c", script], cwd=tmp_path, timeout=3, error_code="download_failed"
        )
    assert error.value.code == code
    assert error.value.message != MediaError("download_failed").message
    assert "never-log-this" not in caplog.text
    assert "cookie-private-value" not in caplog.text
    assert "/private/" not in caplog.text
    assert "stage=download_failed" in caplog.text and "exit=1" in caplog.text
    assert "exception=MediaError" in caplog.text and "traceback=" in caplog.text
