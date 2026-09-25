"""Synthetic kernel-limit probes: run ONLY in the restricted test container.

Required limits: 128MiB RAM/no swap, 32 PIDs, 0.25 CPU. Network disabled.
No real user media or credentials. Intentional child OOM cannot target host data.
"""

import errno
import json
import os
import subprocess
import sys
import time
from pathlib import Path

CGROUP = Path("/sys/fs/cgroup")


def counters(name):
    return dict(line.split() for line in (CGROUP / name).read_text().splitlines())


def main():
    assert (CGROUP / "memory.max").read_text().strip() == "134217728"
    assert (CGROUP / "memory.swap.max").read_text().strip() == "0"
    assert (CGROUP / "pids.max").read_text().strip() == "32"
    assert (CGROUP / "cpu.max").read_text().strip() == "25000 100000"
    assert os.getuid() == 10001
    before = int(counters("memory.events")["oom_kill"])
    memory = subprocess.run(
        [sys.executable, "-c", "x=bytearray(192*1024*1024); print(len(x))"],
        capture_output=True,
        timeout=20,
    )
    after = int(counters("memory.events")["oom_kill"])
    assert memory.returncode == -9 and after > before
    oom_kill_delta = after - before
    children = []
    pid_blocked = False
    try:
        for _ in range(40):
            try:
                children.append(
                    subprocess.Popen(
                        [sys.executable, "-c", "import time; time.sleep(10)"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                )
            except OSError as error:
                assert error.errno == errno.EAGAIN
                pid_blocked = True
                break
        assert pid_blocked
    finally:
        for child in children:
            child.kill()
        for child in children:
            child.wait(timeout=5)
    before = int(counters("cpu.stat")["nr_throttled"])
    end = time.monotonic() + 2
    while time.monotonic() < end:
        pass
    after = int(counters("cpu.stat")["nr_throttled"])
    assert after > before
    print(
        json.dumps(
            {
                "status": "passed",
                "synthetic_reduced_limits": True,
                "oom_kill_delta": oom_kill_delta,
                "pid_creation_denied": pid_blocked,
                "children_reaped": len(children),
                "cpu_throttled_periods_delta": after - before,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
