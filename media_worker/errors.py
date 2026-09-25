"""Stable public errors: never forward subprocess or network diagnostics."""

MESSAGES = {
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
    "download_failed": "Could not download the video. It may be unavailable or require sign-in.",
    "processing_failed": "Could not process the audio.",
    "process_output": "Could not process the source response.",
    "dependency_failed": "The processing service is temporarily unavailable.",
    "invalid_url": "Please send a valid YouTube video link.",
    "playlist": "Please send a link to a single video, not a playlist.",
}


def classify_download_error(stderr: bytes) -> str:
    text = stderr.decode("utf-8", errors="replace").lower()
    groups = (
        ("private", ("private video", "members-only", "members only")),
        ("age_restricted", ("confirm your age", "age-restricted", "age restricted")),
        (
            "region_restricted",
            ("in your country", "in your region", "geo-restricted", "geo restricted"),
        ),
        (
            "unavailable",
            ("video unavailable", "has been removed", "no longer available", "not available"),
        ),
        (
            "cookies_required",
            ("confirm you're not a bot", "login required", "sign in", "use --cookies"),
        ),
    )
    for code, markers in groups:
        if any(marker in text for marker in markers):
            return code
    return "download_failed"


class MediaError(Exception):
    def __init__(self, code: str, message: str | None = None):
        self.code = code
        self.message = message or MESSAGES.get(code, "Could not process the video.")
        super().__init__(self.message)
