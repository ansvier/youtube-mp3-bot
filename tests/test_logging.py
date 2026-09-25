import importlib
import io
import logging


def test_logging_redacts_secrets_urls_and_cookie_lines_in_tracebacks():
    module = importlib.import_module("mp3_bot.logging")
    stream = io.StringIO()
    token = "123456:" + "A" * 35
    module.configure_logging("DEBUG", secrets=(token, "raw-cookie-secret"), stream=stream)
    log = logging.getLogger("mp3_bot.test")
    try:
        raise RuntimeError(
            f"token={token} Cookie: session=raw-cookie-secret\n"
            "https://signed.googlevideo.com/file?sig=private-signature\n"
            ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tprivate-cookie\n"
            "Authorization: Bearer private-auth"
        )
    except RuntimeError:
        log.exception("failed %s", token)
    logging.getLogger("aiogram.event").debug("SECRET UPDATE CONTENT")
    logging.getLogger("aiohttp.client").warning("SECRET DEPENDENCY CONTENT")
    output = stream.getvalue()
    assert "Traceback (most recent call last)" in output
    assert "RuntimeError" in output
    assert "test_logging.py" in output
    for secret in (
        token,
        "raw-cookie-secret",
        "private-signature",
        "private-cookie",
        "private-auth",
        "SECRET UPDATE",
        "SECRET DEPENDENCY",
        "signed.googlevideo",
    ):
        assert secret not in output
    assert "[REDACTED]" in output
