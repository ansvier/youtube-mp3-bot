"""Unicode-safe names, inspired by tg-media-bot's MIT sanitizer.

Unlike upstream, retain NFC spelling and bound UTF-8 bytes, not characters.
"""

import re
import unicodedata


def sanitize_filename(title: str) -> str:
    text = unicodedata.normalize("NFC", title)
    text = "".join(c for c in text if not unicodedata.category(c).startswith("C"))
    text = re.sub(r'[<>:"/\\|?*]', "", text).strip(" .")
    text = re.sub(r"\s+", " ", text)
    if text.lower().endswith(".mp3"):
        text = text[:-4]
    text = text.encode("utf-8")[:176].decode("utf-8", errors="ignore").strip(" .")
    return (text or "audio") + ".mp3"
