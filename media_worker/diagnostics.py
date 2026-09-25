"""Bounded diagnostics without credentials, signed URLs, source text or locals."""

import re
import traceback
from pathlib import PurePath


def scrub_diagnostics(text: str) -> str:
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    text = re.sub(r"(?i)[a-z][a-z0-9+.-]*://[^\s]+", "<url>", text)
    lines = []
    for line in text.splitlines():
        # Suppress entire sensitive lines, including Netscape cookie-jar records.
        if "\t" in line or re.search(
            r"(?i)cookie|authorization|password|token|secret|bearer|api[_-]?key", line
        ):
            lines.append("<credential-related line redacted>")
            continue
        line = re.sub(r'File "[^"]+"', 'File "<path>"', line)
        line = re.sub(r"(?<![\w:])/(?:[^\s\"']+)", "<path>", line)
        line = re.sub(r"\b[A-Za-z0-9_-]{40,}\b", "<opaque value>", line)
        lines.append("".join(c for c in line if c >= " " or c == "\n"))
    return "\n".join(lines)


def safe_traceback(tb=None) -> str:
    frames = traceback.extract_tb(tb) if tb is not None else traceback.extract_stack()[:-1]
    # All frames retained, but never source lines, locals, exception text or full paths.
    return " > ".join(f"{PurePath(f.filename).name}:{f.lineno}:{f.name}" for f in frames)
