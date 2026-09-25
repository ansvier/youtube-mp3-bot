import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        None,
        "http://i.ytimg.com/vi/id/default.jpg",
        "https://evil.com/cover.jpg",
        "https://i.ytimg.com:443/cover.jpg",
        "https://user@i.ytimg.com/cover.jpg",
        "https://i.ytimg.com.evil/cover.jpg",
        "https://i.ytimg.com/../secret",
    ],
)
async def test_cover_rejects_non_allowlisted_urls_without_network(url, monkeypatch):
    from media_worker import thumbnails

    def no_network(*args, **kwargs):
        raise AssertionError("network must not be called")

    monkeypatch.setattr(thumbnails.aiohttp, "ClientSession", no_network)
    assert await thumbnails.fetch_cover(url) is None


class FakeResponse:
    def __init__(self, status, chunks, content_length=None):
        self.status = status
        self.content_length = content_length
        self.content = self
        self.chunks = chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def iter_chunked(self, size):
        for chunk in self.chunks:
            yield chunk


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,chunks,length,expected",
    [
        (200, [b"\xff\xd8\xffpicture"], 10, b"\xff\xd8\xffpicture"),
        (302, [b"\xff\xd8\xffpicture"], 10, None),
        (200, [b"x" * 2_000_001], None, None),
        (200, [], 2_000_001, None),
        (200, [b"not an image"], None, None),
    ],
)
async def test_cover_stream_is_capped_redirects_disabled(
    monkeypatch, status, chunks, length, expected
):
    from media_worker import thumbnails

    class Session:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False
            assert kwargs["timeout"].total <= 15

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def get(self, url, **kwargs):
            assert kwargs["allow_redirects"] is False
            return FakeResponse(status, chunks, length)

    monkeypatch.setattr(thumbnails.aiohttp, "ClientSession", Session)
    assert (
        await thumbnails.fetch_cover("https://i.ytimg.com/vi/dQw4w9WgXcQ/default.jpg") == expected
    )


@pytest.mark.asyncio
async def test_cover_network_timeout_is_nonfatal(monkeypatch):
    from media_worker import thumbnails

    def fail(**kwargs):
        raise TimeoutError

    monkeypatch.setattr(thumbnails.aiohttp, "ClientSession", fail)
    assert await thumbnails.fetch_cover("https://i.ytimg.com/vi/dQw4w9WgXcQ/default.jpg") is None
