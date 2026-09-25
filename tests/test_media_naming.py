import unicodedata


def test_filename_is_nfc_cyrillic_safe_and_byte_bounded():
    from media_worker.naming import sanitize_filename

    name = sanitize_filename("..//Песня: «И\u0306»?*\\\0\n" + "я" * 150)
    assert name.endswith(".mp3")
    assert len(name.encode("utf-8")) <= 180
    assert "Песня" in name and "Й" in name
    assert unicodedata.is_normalized("NFC", name)
    assert not any(c in name for c in "/\\:*?\0\n")
    assert not name.startswith(".")
    assert sanitize_filename("... /<>:") == "audio.mp3"
    assert sanitize_filename("track.mp3") == "track.mp3"
