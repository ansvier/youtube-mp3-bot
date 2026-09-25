import json
import os
import subprocess
import sys


def test_check_cli_validates_dependencies_and_settings_without_network(tmp_path):
    env = os.environ | {"TEMP_DIR": str(tmp_path / "worker"), "MAX_FILE_SIZE_MB": ""}
    env.pop("BOT_TOKEN", None)
    result = subprocess.run(
        [sys.executable, "-m", "media_worker", "--check"],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "status": "ok",
        "tools": ["yt-dlp", "ffmpeg", "ffprobe", "deno"],
    }
    assert list((tmp_path / "worker").iterdir()) == []
    env["DEFAULT_AUDIO_BITRATE"] = "999"
    result = subprocess.run(
        [sys.executable, "-m", "media_worker", "--check"],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert str(tmp_path) not in result.stderr


def test_worker_cli_healthcheck_and_graceful_sigterm(tmp_path):
    import socket
    import time
    import urllib.request

    with socket.socket() as check_socket:
        check_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        check_socket.bind(("127.0.0.1", 8080))
    env = os.environ | {"TEMP_DIR": str(tmp_path / "worker"), "MAX_FILE_SIZE_MB": ""}
    env.pop("BOT_TOKEN", None)
    process = subprocess.Popen(
        [sys.executable, "-m", "media_worker"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        ready = False
        for _ in range(50):
            if process.poll() is not None:
                break
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:8080/health", timeout=0.2
                ) as response:
                    ready = json.load(response) == {"status": "ok"}
                break
            except OSError:
                time.sleep(0.05)
        assert ready, "worker must start listening on 8080"
        health = subprocess.run(
            [sys.executable, "-m", "media_worker", "--healthcheck"],
            env=env,
            capture_output=True,
            timeout=10,
        )
        assert health.returncode == 0, health.stderr
        process.terminate()
        process.wait(timeout=5)
        assert process.returncode == 0
        assert list((tmp_path / "worker").iterdir()) == []
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)
