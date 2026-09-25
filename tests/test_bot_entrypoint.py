import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_bot import TOKEN, settings

ROOT = Path(__file__).resolve().parents[1]


def cli(tmp_path, *arguments, valid=True):
    env = {**os.environ, "PYTHONPATH": str(ROOT), "TEMP_DIR": str(tmp_path)}
    env.pop("BOT_TOKEN", None)
    env.pop("ALLOWED_USER_IDS", None)
    if valid:
        env.update(BOT_TOKEN=TOKEN, ALLOWED_USER_IDS="10")
    return subprocess.run(
        [sys.executable, "-m", "mp3_bot", *arguments],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_help_is_english_without_configuration(tmp_path):
    result = cli(tmp_path, "--help", valid=False)
    assert result.returncode == 0, result.stderr
    assert "Private YouTube to MP3 bot" in result.stdout
    assert "Check configuration without network access" in result.stdout
    assert "Check the process heartbeat" in result.stdout
    assert "--check" in result.stdout and "--healthcheck" in result.stdout
    assert not result.stderr
    assert not list(tmp_path.iterdir())


def test_check_is_network_free_and_does_not_disclose_token(tmp_path):
    result = cli(tmp_path, "--check")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "Bot configuration and dependencies verified.\n"
    assert TOKEN not in result.stdout + result.stderr
    assert not list(tmp_path.iterdir())


def test_check_fails_closed_and_import_does_not_load_config(tmp_path):
    result = cli(tmp_path, "--check", valid=False)
    assert result.returncode == 1
    assert "Invalid setting BOT_TOKEN" in result.stdout + result.stderr
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    env.pop("BOT_TOKEN", None)
    result = subprocess.run(
        [sys.executable, "-c", "import mp3_bot; import mp3_bot.__main__; import mp3_bot.app"],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert not result.stdout


@pytest.mark.asyncio
async def test_custom_telegram_api_uses_http_upload_not_shared_paths(tmp_path):
    module = importlib.import_module("mp3_bot.__main__")
    bot = module.create_bot(settings(tmp_path, TELEGRAM_API_BASE_URL="http://telegram:8081"))
    try:
        assert bot.session.api.is_local is False
        assert bot.session.api.api_url(TOKEN, "sendAudio").startswith("http://telegram:8081/bot")
    finally:
        await bot.session.close()
