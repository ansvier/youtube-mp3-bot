"""Distribution helpers must not embed personal machine paths."""

import re
from pathlib import Path


def test_container_probe_has_no_personal_home_path():
    script = Path(__file__).resolve().parents[1] / "scripts" / "verify_containers.py"
    assert not re.search(r"/(?:Users|home)/[A-Za-z0-9_.-]+", script.read_text())
