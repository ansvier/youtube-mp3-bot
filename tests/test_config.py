import importlib

import pytest


@pytest.mark.parametrize(
    "field,value",
    [
        ("BOT_TOKEN", ""),
        ("BOT_TOKEN", "fake"),
        ("BOT_TOKEN", "123:secret"),
        ("ALLOWED_USER_IDS", ""),
        ("ALLOWED_USER_IDS", "1,"),
        ("ALLOWED_USER_IDS", "-1"),
        ("ALLOWED_USER_IDS", "0"),
        ("ALLOWED_USER_IDS", "1,abc"),
        ("ALLOWED_USER_IDS", "1,2.5"),
        ("ALLOWED_USER_IDS", "+1"),
        ("ALLOWED_USER_IDS", "１２３"),
        ("QUEUE_SIZE", "0"),
        ("UPLOAD_TIMEOUT", "-1"),
        ("MAX_CONCURRENT_DOWNLOADS", "0"),
        ("DOWNLOAD_TIMEOUT", "abc"),
        ("CONVERSION_TIMEOUT", "0"),
        ("DEFAULT_AUDIO_BITRATE", "1000"),
        ("DEFAULT_AUDIO_BITRATE", "160"),
        ("DEFAULT_AUDIO_BITRATE", "256"),
        ("DEFAULT_AUDIO_BITRATE", "320"),
        ("MAX_FILE_SIZE_MB", "51"),
        ("LOG_LEVEL", "chatty"),
        ("TELEGRAM_API_BASE_URL", "ftp://host"),
        ("TELEGRAM_API_BASE_URL", "http://user:secret@host"),
        ("TELEGRAM_API_BASE_URL", "http://@host"),
        ("TELEGRAM_API_BASE_URL", "http://host/?secret=x"),
        ("TELEGRAM_API_BASE_URL", "http://host/#x"),
        ("TELEGRAM_API_BASE_URL", "http://"),
        ("MEDIA_WORKER_URL", "http://user:secret@host"),
    ],
)
def test_invalid_config_fails_closed_without_echoing_value(field, value):
    from mp3_bot.config import Settings

    env = {"BOT_TOKEN": "123456:" + "A" * 35, "ALLOWED_USER_IDS": "10", field: value}
    with pytest.raises(ValueError) as error:
        Settings.from_env(env)
    assert str(error.value) == f"Invalid setting {field}"
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("missing", ["BOT_TOKEN", "ALLOWED_USER_IDS"])
def test_required_config_missing(missing):
    from mp3_bot.config import Settings

    env = {"BOT_TOKEN": "123456:" + "A" * 35, "ALLOWED_USER_IDS": "10"}
    del env[missing]
    with pytest.raises(ValueError, match=f"^Invalid setting {missing}$"):
        Settings.from_env(env)


def test_operator_overrides_and_custom_api_size_limit():
    from mp3_bot.config import Settings

    env = {
        "BOT_TOKEN": "123456:" + "A" * 35,
        "ALLOWED_USER_IDS": "10,10",
        "TELEGRAM_API_BASE_URL": "http://telegram:8081/",
        "MAX_CONCURRENT_DOWNLOADS": "2",
        "DOWNLOAD_TIMEOUT": "90",
        "CONVERSION_TIMEOUT": "60",
        "DEFAULT_AUDIO_BITRATE": "128",
        "TEMP_DIR": "/tmp/test-bot",
        "LOG_LEVEL": "DEBUG",
        "COOKIES_FILE": "/private/cookies.txt",
        "MEDIA_WORKER_URL": "http://worker:9000/",
        "RATE_LIMIT_SECONDS": "0",
        "QUEUE_SIZE": "3",
        "UPLOAD_TIMEOUT": "40",
    }
    settings = Settings.from_env(env)
    assert settings.max_file_size_mb == 2000
    assert settings.telegram_api_base_url == "http://telegram:8081"
    assert settings.media_worker_url == "http://worker:9000"
    assert settings.default_audio_bitrate == 128
    assert settings.max_concurrent_downloads == 2
    assert settings.download_timeout == 90
    assert settings.conversion_timeout == 60
    assert settings.rate_limit_seconds == 0
    assert settings.queue_size == 3
    assert settings.upload_timeout == 40
    assert str(settings.temp_dir) == "/tmp/test-bot"
    assert settings.cookies_file == "/private/cookies.txt"
    assert settings.log_level == "DEBUG"
    assert settings.allowed_user_ids == frozenset({10})
    with pytest.raises(ValueError, match="MAX_FILE_SIZE_MB"):
        Settings.from_env({**env, "MAX_FILE_SIZE_MB": "2001"})


@pytest.mark.parametrize(
    "url", ["https://api.telegram.org", "https://API.TELEGRAM.ORG/", "http://api.telegram.org:80"]
)
def test_explicit_official_api_is_not_a_local_large_file_server(url):
    from mp3_bot.config import Settings

    env = {
        "BOT_TOKEN": "123456:" + "A" * 35,
        "ALLOWED_USER_IDS": "10",
        "TELEGRAM_API_BASE_URL": url,
    }
    assert Settings.from_env(env).max_file_size_mb == 50
    with pytest.raises(ValueError, match="MAX_FILE_SIZE_MB"):
        Settings.from_env({**env, "MAX_FILE_SIZE_MB": "51"})


def test_blank_file_limit_selects_api_default():
    from mp3_bot.config import Settings

    env = {"BOT_TOKEN": "123456:" + "A" * 35, "ALLOWED_USER_IDS": "10", "MAX_FILE_SIZE_MB": ""}
    assert Settings.from_env(env).max_file_size_mb == 50
    assert (
        Settings.from_env({**env, "TELEGRAM_API_BASE_URL": "http://api:8081"}).max_file_size_mb
        == 2000
    )


def test_config_defaults_are_private_and_bounded():
    config = importlib.import_module("mp3_bot.config")
    settings = config.Settings.from_env(
        {"BOT_TOKEN": "123456:" + "A" * 35, "ALLOWED_USER_IDS": "10, 20"}
    )
    assert settings.allowed_user_ids == frozenset({10, 20})
    assert settings.max_concurrent_downloads == 1
    assert settings.download_timeout == 600
    assert settings.conversion_timeout == 300
    assert settings.default_audio_bitrate == 192
    assert settings.max_file_size_mb == 50
    assert str(settings.temp_dir) == "/tmp/mp3-bot"
    assert settings.log_level == "INFO"
    assert settings.cookies_file is None
    assert settings.telegram_api_base_url is None
    assert settings.media_worker_url == "http://worker:8080"
    assert settings.rate_limit_seconds == 30
    assert settings.queue_size == 5
    assert settings.upload_timeout == 300
    assert "A" * 35 not in repr(settings)
