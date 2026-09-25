import pytest
from test_media_errors import WORKER_MESSAGES

BOT_MESSAGES = {
    "upload_failed": "Could not send the MP3 to Telegram. Please try again later.",
    "file_too_large": "The file exceeds the size limit. Please choose a shorter video.",
    "too_large": "The file exceeds the size limit. Please choose a shorter video.",
    "worker_unavailable": "The processing service is temporarily unavailable. Please try again later.",
    "worker_timeout": "Processing took too long. Please try a shorter video.",
    "invalid_response": "The processing service returned an invalid response. Please try again later.",
}


@pytest.mark.parametrize(
    "code,expected",
    {
        **BOT_MESSAGES,
        **WORKER_MESSAGES,
        "unknown": "Could not process the video. Please try again later.",
        "UNTRUSTED RAW PRIVATE URL": "Could not process the video. Please try again later.",
    }.items(),
)
def test_public_messages_are_english_and_keep_worker_code_precedence(code, expected):
    from mp3_bot.errors import public_message

    assert public_message(code) == expected


def test_bot_error_catalog_is_english_including_shadowed_size_message():
    from mp3_bot.errors import PUBLIC_MESSAGES

    assert PUBLIC_MESSAGES == BOT_MESSAGES
