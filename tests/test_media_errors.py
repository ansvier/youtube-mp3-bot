import pytest

WORKER_MESSAGES = {
    "private": "This is a private video. Access is restricted by its owner.",
    "unavailable": "The video has been removed or is unavailable.",
    "age_restricted": "This video is age-restricted and requires authorized sign-in.",
    "region_restricted": "This video is unavailable in the server's region.",
    "cookies_required": "YouTube requires sign-in. Please contact the administrator.",
    "busy": "The service is busy. Please try again shortly.",
    "timeout": "Processing timed out. Please try a shorter video.",
    "too_large": "The MP3 exceeds the size limit. Please choose a shorter video.",
    "source_too_large": "The source file is too large to process.",
    "live": "Live and scheduled streams are not supported.",
    "invalid_request": "Invalid request to the processing service.",
    "download_failed": ("Could not download the video. It may be unavailable or require sign-in."),
    "processing_failed": "Could not process the audio.",
    "process_output": "Could not process the source response.",
    "dependency_failed": "The processing service is temporarily unavailable.",
    "invalid_url": "Please send a valid YouTube video link.",
    "playlist": "Please send a link to a single video, not a playlist.",
}


@pytest.mark.parametrize(
    "code,expected",
    [*WORKER_MESSAGES.items(), ("unknown", "Could not process the video.")],
)
def test_public_error_codes_have_safe_english_messages(code, expected):
    from media_worker.errors import MediaError

    error = MediaError(code)
    assert error.code == code
    assert error.message == expected
    assert str(error) == expected
    assert len(error.message) < 300
