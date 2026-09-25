def test_diagnostics_scrub_cookie_jars_paths_and_signed_urls():
    from media_worker.diagnostics import scrub_diagnostics

    raw = (
        "request https://host/path?signature=SIGNED-VALUE\n"
        "Cookie: SID=COOKIE-VALUE\nAuthorization: Bearer BEARER-VALUE\n"
        ".youtube.com\tTRUE\t/\tFALSE\t0\tSID\tJAR-VALUE\n"
        'File "/private/job/path.py", line 2\n'
        "ERROR: unavailable"
    )
    safe = scrub_diagnostics(raw)
    for secret in ("SIGNED-VALUE", "COOKIE-VALUE", "BEARER-VALUE", "JAR-VALUE", "/private/job/"):
        assert secret not in safe
    assert "ERROR: unavailable" in safe
