import asyncio
import json
import shutil
import subprocess

import pytest
from mutagen.id3 import ID3
from mutagen.mp3 import MP3


@pytest.fixture
def synthetic_media(tmp_path):
    assert shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg fixture tests are mandatory"
    source = tmp_path / "source.wav"
    cover = tmp_path / "cover.jpg"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            "-c:a",
            "pcm_s16le",
            str(source),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64",
            "-frames:v",
            "1",
            "-threads",
            "1",
            str(cover),
        ],
        check=True,
    )
    return source, cover


@pytest.mark.asyncio
async def test_real_ffmpeg_cyrillic_tags_cover_and_actual_duration(synthetic_media):
    from media_worker.config import MediaConfig
    from media_worker.encoding import encode_source
    from media_worker.models import MediaInfo

    source, cover = synthetic_media
    info = MediaInfo("Песня «Тест»", "Исполнитель", 999)
    result = await encode_source(source, info, MediaConfig(), cover=cover.read_bytes())
    assert result.bitrate == 192
    assert result.filename == "Песня «Тест».mp3"
    assert 2.9 <= result.info.duration <= 3.2
    audio = MP3(result.path)
    assert 185000 <= audio.info.bitrate <= 195000
    tags = ID3(result.path)
    assert tags["TIT2"].text == ["Песня «Тест»"]
    assert tags["TPE1"].text == ["Исполнитель"]
    assert tags.getall("APIC")[0].data == cover.read_bytes()
    probe = await asyncio.to_thread(
        subprocess.run,
        ["ffprobe", "-v", "error", "-show_format", "-of", "json", str(result.path)],
        check=True,
        capture_output=True,
    )
    assert float(json.loads(probe.stdout)["format"]["duration"]) == result.info.duration


@pytest.mark.asyncio
@pytest.mark.parametrize("initial,next_bitrate", [(192, 128), (128, 96), (96, 64), (64, None)])
async def test_actual_tagged_size_boundary_and_fallback_from_source(
    synthetic_media, monkeypatch, initial, next_bitrate
):
    from dataclasses import replace

    from media_worker import encoding
    from media_worker.config import MediaConfig
    from media_worker.errors import MediaError
    from media_worker.models import MediaInfo

    source, cover = synthetic_media
    info = MediaInfo("Тест", "Автор", None)
    config = MediaConfig(default_bitrate=initial)
    first = await encoding.encode_source(source, info, config, cover=cover.read_bytes())
    size = first.path.stat().st_size
    exact = await encoding.encode_source(
        source, info, replace(config, max_file_bytes=size), cover=cover.read_bytes()
    )
    assert exact.bitrate == initial
    calls = []
    original = encoding.run_process

    async def recording_run(args, **kwargs):
        calls.append(args)
        return await original(args, **kwargs)

    monkeypatch.setattr(encoding, "run_process", recording_run)
    if next_bitrate is None:
        with pytest.raises(MediaError) as error:
            await encoding.encode_source(
                source, info, replace(config, max_file_bytes=size - 1), cover=cover.read_bytes()
            )
        assert error.value.code == "too_large"
    else:
        result = await encoding.encode_source(
            source, info, replace(config, max_file_bytes=size - 1), cover=cover.read_bytes()
        )
        assert result.bitrate == next_bitrate
        assert result.path.stat().st_size <= size - 1
    ffmpeg_calls = [args for args in calls if args[0] == "ffmpeg"]
    assert all(args[args.index("-i") + 1] == str(source) for args in ffmpeg_calls)
    assert all("-t" in args and "-format_whitelist" in args for args in ffmpeg_calls)


@pytest.mark.asyncio
async def test_local_api_never_downshifts(synthetic_media):
    from dataclasses import replace

    from media_worker.config import MediaConfig
    from media_worker.encoding import encode_source
    from media_worker.errors import MediaError
    from media_worker.models import MediaInfo

    source, _ = synthetic_media
    info = MediaInfo("Тест", "", None)
    config = MediaConfig(local_api=True)
    first = await encode_source(source, info, config)
    cap = first.path.stat().st_size - 1
    with pytest.raises(MediaError) as error:
        await encode_source(source, info, replace(config, max_file_bytes=cap))
    assert error.value.code == "too_large"
    assert str(error.value) == "The MP3 exceeds the configured local API size limit."


@pytest.mark.asyncio
async def test_invalid_cover_is_nonfatal(synthetic_media):
    from media_worker.config import MediaConfig
    from media_worker.encoding import encode_source
    from media_worker.models import MediaInfo

    source, _ = synthetic_media
    result = await encode_source(
        source, MediaInfo("x", "", None), MediaConfig(), cover=b"not an image"
    )
    assert not ID3(result.path).getall("APIC")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "container,codec", [("webm", "libopus"), ("mp4", "aac"), ("mpegts", "aac")]
)
async def test_real_common_youtube_audio_containers(synthetic_media, container, codec):
    from media_worker.config import MediaConfig
    from media_worker.encoding import encode_source
    from media_worker.models import MediaInfo
    from media_worker.process import run_process

    wave, _ = synthetic_media
    source = wave.parent / "source.media"
    await run_process(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(wave),
            "-c:a",
            codec,
            "-threads",
            "1",
            "-f",
            container,
            str(source),
        ],
        cwd=wave.parent,
        timeout=5,
    )
    result = await encode_source(source, MediaInfo("Контейнер", "", None), MediaConfig())
    assert result.path.stat().st_size > 1000
    assert 2.8 < result.info.duration < 3.3


@pytest.mark.asyncio
async def test_partial_cover_tag_failure_preserves_clean_audio(synthetic_media, monkeypatch):
    from media_worker.config import MediaConfig
    from media_worker.encoding import encode_source
    from media_worker.models import MediaInfo

    source, cover = synthetic_media
    original_save = ID3.save

    def fail_cover_save(tags, filename, **kwargs):
        if tags.getall("APIC"):
            filename.write_bytes(b"partial corrupted cover write")
            raise OSError("cover write failed")
        return original_save(tags, filename, **kwargs)

    monkeypatch.setattr(ID3, "save", fail_cover_save)
    result = await encode_source(
        source, MediaInfo("Видео", "Автор", None), MediaConfig(), cover=cover.read_bytes()
    )
    assert MP3(result.path).info.length > 2.8
    tags = ID3(result.path)
    assert tags["TIT2"].text == ["Видео"]
    assert tags["TPE1"].text == ["Автор"]
    assert not tags.getall("APIC")
