import pytest


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com.evil.com/watch?v=dQw4w9WgXcQ",
        "https://user@youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com:443/watch?v=dQw4w9WgXcQ",
        "file://youtube.com/watch?v=dQw4w9WgXcQ",
        "https://yоutube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=short",
        "https://youtube.com/watch?v=%64Qw4w9WgXcQ",
        "https://youtube.com/watch?%76=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=dQw4w9WgXcQ&v=AAAAAAAAAAA",
        "https://youtube.com/../watch?v=dQw4w9WgXcQ",
        "https://youtube.com/%77atch?v=dQw4w9WgXcQ",
        "https://youtube.com\\@evil.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/playlist?list=abc",
        "https://youtube.com/watch?list=abc",
        "https://youtube.com/watch?v=dQw4w9WgXcQ\n",
    ],
)
def test_unsafe_or_nonvideo_urls_are_rejected(url):
    from media_worker.errors import MediaError
    from media_worker.urls import validate_url

    with pytest.raises(MediaError) as error:
        validate_url(url)
    assert error.value.code in {"invalid_url", "playlist"}
    assert url not in error.value.message


@pytest.mark.parametrize(
    "url",
    [
        "http://youtube.com/watch?v=dQw4w9WgXcQ",
        "https://m.youtube.com/shorts/dQw4w9WgXcQ?feature=share",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://youtube.com/live/dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?si=x",
        "https://www.youtu.be/dQw4w9WgXcQ",
    ],
)
def test_supported_variants(url):
    from media_worker.urls import validate_url

    assert validate_url(url) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_extract_first_counts_all_links_and_handles_bare_youtube():
    from media_worker.urls import extract_first

    result = extract_first("Вот (youtu.be/dQw4w9WgXcQ), затем https://example.com/x")
    assert result.url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert result.count == 2


def test_extract_does_not_skip_non_youtube_first_link():
    from media_worker.errors import MediaError
    from media_worker.urls import extract_first

    with pytest.raises(MediaError):
        extract_first("https://example.com/x https://youtu.be/dQw4w9WgXcQ")
    with pytest.raises(MediaError):
        extract_first("без ссылок")
    with pytest.raises(MediaError):
        extract_first("evilyoutube.com/watch?v=dQw4w9WgXcQ")
    with pytest.raises(MediaError):
        extract_first("ftp://youtube.com/watch?v=dQw4w9WgXcQ https://youtu.be/dQw4w9WgXcQ")
    with pytest.raises(MediaError):
        extract_first("https:// https://youtu.be/dQw4w9WgXcQ")


def test_watch_url_is_canonical_without_playlist_context():
    from media_worker.urls import validate_url

    assert validate_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123&t=5") == (
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    )
