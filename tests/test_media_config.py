from pathlib import Path

import pytest


def test_config_safe_defaults_and_local_capacity():
    from media_worker.config import MediaConfig

    assert MediaConfig.from_env({"MAX_FILE_SIZE_MB": ""}).max_file_bytes == 50_000_000
    assert (
        MediaConfig.from_env(
            {"MAX_FILE_SIZE_MB": "", "TELEGRAM_API_BASE_URL": "http://local"}
        ).max_file_bytes
        == 2_000_000_000
    )
    config = MediaConfig.from_env({})
    assert config.max_file_bytes == 50_000_000
    assert config.max_source_bytes == 512_000_000
    assert config.default_bitrate == 192
    assert config.max_concurrent == 1
    assert config.download_timeout == 600
    assert config.conversion_timeout == 300
    assert config.temp_dir == Path("/tmp/mp3-worker")
    assert not config.local_api
    local = MediaConfig.from_env({"TELEGRAM_API_BASE_URL": "http://telegram-api:8081"})
    assert local.local_api and local.max_file_bytes == 2_000_000_000
    assert MediaConfig.from_env({"MAX_FILE_SIZE_MB": "45"}).max_file_bytes == 45_000_000


@pytest.mark.parametrize(
    "key,value",
    [
        ("MAX_CONCURRENT_DOWNLOADS", "0"),
        ("DOWNLOAD_TIMEOUT", "-1"),
        ("CONVERSION_TIMEOUT", "nan"),
        ("MAX_FILE_SIZE_MB", "inf"),
        ("MAX_SOURCE_SIZE_MB", "0"),
        ("DEFAULT_AUDIO_BITRATE", "256"),
        ("DEFAULT_AUDIO_BITRATE", "bad"),
        ("COOKIES_FILE", "/not/a/cookie/file"),
    ],
)
def test_config_rejects_invalid_values(key, value):
    from media_worker.config import MediaConfig

    with pytest.raises(ValueError):
        MediaConfig.from_env({key: value})


def test_official_api_is_cloud_and_cap_is_bounded():
    from media_worker.config import MediaConfig

    config = MediaConfig.from_env({"TELEGRAM_API_BASE_URL": "https://api.telegram.org"})
    assert config.local_api is False and config.max_file_bytes == 50_000_000
    with pytest.raises(ValueError):
        MediaConfig.from_env({"MAX_FILE_SIZE_MB": "50.000001"})
    with pytest.raises(ValueError):
        MediaConfig.from_env(
            {"TELEGRAM_API_BASE_URL": "http://local:8081", "MAX_FILE_SIZE_MB": "2001"}
        )


@pytest.mark.parametrize(
    "base",
    [
        "ftp://local",
        "https://user:pass@local",
        "http://local/?token=x",
        "http://local/#frag",
        "not-a-url",
    ],
)
def test_api_base_requires_structural_http_url(base):
    from media_worker.config import MediaConfig

    with pytest.raises(ValueError):
        MediaConfig.from_env({"TELEGRAM_API_BASE_URL": base})
