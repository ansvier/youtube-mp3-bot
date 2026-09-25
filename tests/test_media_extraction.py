import json

import pytest

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.mark.asyncio
async def test_extractor_uses_locked_args_and_bounded_metadata(tmp_path, monkeypatch):
    from media_worker import extraction
    from media_worker.config import MediaConfig
    from media_worker.process import ProcessResult

    calls = []

    async def fake_process(args, **kwargs):
        calls.append((args, kwargs))
        return ProcessResult(
            json.dumps(
                {
                    "title": "Я" * 5000,
                    "artist": "Автор\n\x00",
                    "duration": 42.5,
                    "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/default.jpg",
                }
            ).encode(),
            b"",
            0,
        )

    monkeypatch.setattr(extraction, "run_process", fake_process)
    config = MediaConfig()
    metadata = await extraction.Extractor(config).info(URL, tmp_path)
    assert len(metadata.info.title.encode()) <= 512
    assert metadata.info.performer == "Автор"
    assert metadata.info.duration == 42.5
    args, kwargs = calls[0]
    for flag in (
        "--ignore-config",
        "--no-playlist",
        "--no-cache-dir",
        "--no-progress",
        "--no-remote-components",
        "--no-plugin-dirs",
    ):
        assert flag in args
    assert args[args.index("--use-extractors") + 1] == "Youtube"
    assert args[args.index("--format") + 1] == "bestaudio"
    assert args[args.index("--downloader") + 1] == "native"
    assert args[args.index("--ffmpeg-location") + 1] == str(tmp_path)
    assert args[-2:] == ["--", URL]
    assert kwargs["output_limit"] <= 4_000_000
    assert kwargs["timeout"] <= config.download_timeout


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw,code",
    [
        ({"is_live": True}, "live"),
        ({"live_status": "is_upcoming"}, "live"),
        ({"_type": "playlist", "entries": []}, "playlist"),
        ({"filesize": 512_000_001}, "source_too_large"),
        ({"requested_downloads": [{"filesize": 512_000_001}]}, "source_too_large"),
    ],
)
async def test_extractor_rejects_unbounded_sources(tmp_path, monkeypatch, raw, code):
    from media_worker import extraction
    from media_worker.config import MediaConfig
    from media_worker.errors import MediaError
    from media_worker.process import ProcessResult

    async def fake_process(*args, **kwargs):
        return ProcessResult(json.dumps(raw).encode(), b"", 0)

    monkeypatch.setattr(extraction, "run_process", fake_process)
    with pytest.raises(MediaError) as error:
        await extraction.Extractor(MediaConfig()).info(URL, tmp_path)
    assert error.value.code == code


@pytest.mark.asyncio
async def test_download_uses_fixed_path_cookie_copy_and_disk_watchdog(tmp_path, monkeypatch):
    from media_worker import extraction
    from media_worker.config import MediaConfig
    from media_worker.process import ProcessResult

    cookie = tmp_path / "cookies.txt"
    cookie.write_text("# cookies")

    async def fake_process(args, **kwargs):
        assert args[args.index("--output") + 1] == str(tmp_path / "source.media")
        assert args[args.index("--cookies") + 1] == str(cookie)
        assert "--write-thumbnail" not in args
        assert args[args.index("--max-filesize") + 1] == "512000000"
        assert kwargs["disk_limit"] <= 520_000_000
        assert args[-1] == URL
        (tmp_path / "source.media").write_bytes(b"synthetic media, not a download")
        return ProcessResult(b"", b"", 0)

    monkeypatch.setattr(extraction, "run_process", fake_process)
    source = await extraction.Extractor(MediaConfig()).download(URL, tmp_path, cookie)
    assert source == tmp_path / "source.media"


@pytest.mark.asyncio
async def test_missing_or_symlink_source_is_rejected(tmp_path, monkeypatch):
    from media_worker import extraction
    from media_worker.config import MediaConfig
    from media_worker.errors import MediaError
    from media_worker.process import ProcessResult

    async def fake_process(*args, **kwargs):
        return ProcessResult(b"", b"", 0)

    monkeypatch.setattr(extraction, "run_process", fake_process)
    with pytest.raises(MediaError):
        await extraction.Extractor(MediaConfig()).download(URL, tmp_path)
    (tmp_path / "source.media").symlink_to(__file__)
    with pytest.raises(MediaError):
        await extraction.Extractor(MediaConfig()).download(URL, tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw,expected",
    [
        ({}, "Audio"),
        ({"title": None}, "Audio"),
        ({"title": ""}, "Audio"),
        ({"title": 123}, "Audio"),
        ({"title": "\x00\n"}, "Audio"),
        ({"title": "", "track": "曲名 🎵"}, "曲名 🎵"),
    ],
)
async def test_missing_title_uses_english_fallback_without_translating_track(
    tmp_path, monkeypatch, raw, expected
):
    from media_worker import extraction
    from media_worker.config import MediaConfig
    from media_worker.naming import sanitize_filename
    from media_worker.process import ProcessResult

    async def fake_process(*args, **kwargs):
        return ProcessResult(json.dumps(raw).encode(), b"", 0)

    monkeypatch.setattr(extraction, "run_process", fake_process)
    result = await extraction.Extractor(MediaConfig()).info(URL, tmp_path)
    assert result.info.title == expected
    assert result.info.performer == ""
    assert sanitize_filename(result.info.title) == f"{expected}.mp3"


@pytest.mark.asyncio
async def test_video_title_takes_priority_over_music_track(tmp_path, monkeypatch):
    from media_worker import extraction
    from media_worker.config import MediaConfig
    from media_worker.process import ProcessResult

    async def fake_process(*args, **kwargs):
        return ProcessResult(
            json.dumps({"title": "Название видео", "track": "Название трека"}).encode(), b"", 0
        )

    monkeypatch.setattr(extraction, "run_process", fake_process)
    result = await extraction.Extractor(MediaConfig()).info(URL, tmp_path)
    assert result.info.title == "Название видео"
