"""Public messages are selected by code, never by network diagnostics."""

from media_worker.errors import MESSAGES

PUBLIC_MESSAGES = {
    "upload_failed": "Could not send the MP3 to Telegram. Please try again later.",
    "file_too_large": "The file exceeds the size limit. Please choose a shorter video.",
    "too_large": "The file exceeds the size limit. Please choose a shorter video.",
    "worker_unavailable": "The processing service is temporarily unavailable. Please try again later.",
    "worker_timeout": "Processing took too long. Please try a shorter video.",
    "invalid_response": "The processing service returned an invalid response. Please try again later.",
}


def public_message(code: str) -> str:
    return MESSAGES.get(
        code, PUBLIC_MESSAGES.get(code, "Could not process the video. Please try again later.")
    )
