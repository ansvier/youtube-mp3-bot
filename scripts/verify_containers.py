"""Token-free smoke for already-built images; run from the project root.

Starts ONLY an isolated verification worker, never Telegram polling. Removes only
its own Compose project in finally. Existing bot services are not touched.
"""

import json
import os
import subprocess
import time
from pathlib import Path

PROJECT = "private-mp3-verification"
ENV = dict(os.environ)
ENV.update(
    BOT_TOKEN="123456789:" + "A" * 35,
    ALLOWED_USER_IDS="123456",
    TELEGRAM_API_BASE_URL="",
    COOKIES_FILE="",
    MAX_CONCURRENT_DOWNLOADS="1",
    MAX_FILE_SIZE_MB="",
    TEMP_DIR="/tmp/mp3-bot",
)
COMPOSE = ["docker", "compose", "-p", PROJECT, "--env-file", ".env.example"]
REPORT = Path("artifacts/container-smoke.json")


def command(args, *, expected=0, timeout=90):
    result = subprocess.run(args, env=ENV, capture_output=True, text=True, timeout=timeout)
    expected_codes = expected if isinstance(expected, tuple) else (expected,)
    if result.returncode not in expected_codes:
        raise RuntimeError(f"Unexpected exit {result.returncode}: {result.stderr[-4000:]}")
    return result.stdout.strip()


def run_image(image, *args, allowed=True):
    config = [
        "docker",
        "run",
        "--rm",
        "--init",
        "--network",
        "none",
        "--read-only",
        "--user",
        "10001:10001",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "128",
        "--memory",
        "512m",
        "--memory-swap",
        "512m",
        "--cpus",
        "1",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=128m,mode=1777",
        "-e",
        "BOT_TOKEN",
    ]
    if allowed:
        config.extend(["-e", "ALLOWED_USER_IDS"])
    return command(config + [image, *args], expected=0 if allowed else 1)


def main():
    report = {"status": "running", "real_telegram": False, "real_youtube": False}
    try:
        report["bot_check"] = run_image(
            "private-youtube-mp3-bot:local", "python", "-m", "mp3_bot", "--check"
        )
        run_image(
            "private-youtube-mp3-bot:local", "python", "-m", "mp3_bot", "--check", allowed=False
        )
        report["missing_allowlist_rejected"] = True
        command(COMPOSE + ["up", "-d", "--no-build", "--wait", "--wait-timeout", "60", "worker"])
        cid = command(COMPOSE + ["ps", "-q", "worker"])
        assert cid
        info = json.loads(command(["docker", "inspect", cid]))[0]
        assert info["State"]["Health"]["Status"] == "healthy"
        host = info["HostConfig"]
        assert host["ReadonlyRootfs"] and host["Init"]
        assert host["CapDrop"] == ["ALL"]
        assert host["RestartPolicy"]["Name"] == "unless-stopped"
        assert not host["Binds"] and not host["PortBindings"]
        assert not any(
            v.startswith(("BOT_TOKEN=", "ALLOWED_USER_IDS=")) for v in info["Config"]["Env"]
        )
        report["worker_image"] = info["Image"]
        report["worker_health"] = "healthy"
        report["worker_has_token_or_user_ids"] = False
        report["worker_tools"] = json.loads(
            command(["docker", "exec", cid, "python", "-m", "media_worker", "--check"])
        )
        probe = """import json,os
from pathlib import Path
status=dict(line.split(":",1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
limits={name:Path("/sys/fs/cgroup",name).read_text().strip() for name in ("memory.max","memory.swap.max","pids.max","cpu.max")}
assert os.getuid()==10001
assert int(status["CapEff"],16)==0 and status["NoNewPrivs"].strip()=="1" and status["Seccomp"].strip()=="2"
assert limits=={"memory.max":"2147483648","memory.swap.max":"0","pids.max":"128","cpu.max":"200000 100000"}
try:
    Path("/app/containment-probe").write_text("test")
except OSError:
    pass
else:
    raise AssertionError("rootfs writable")
assert not Path("/Users").exists()
Path("/tmp/worker-isolation-proof").write_text("synthetic-only")
assert Path("/tmp/worker-isolation-proof").read_text()=="synthetic-only"
print(json.dumps({"uid":os.getuid(),"cap_eff":status["CapEff"].strip(),"no_new_privs":1,"seccomp":2,"cgroup":limits,"rootfs_write_denied":True,"host_home_absent":True}))"""
        report["runtime_restrictions"] = json.loads(
            command(["docker", "exec", cid, "python", "-c", probe])
        )
        run_image(
            "private-youtube-mp3-bot:local",
            "python",
            "-c",
            "from pathlib import Path; assert not Path('/tmp/worker-isolation-proof').exists()",
        )
        report["sibling_tmp_isolation"] = True
        # Crash the application, not `docker kill`: a manual daemon stop suppresses
        # restart policy. PID 1 is Docker's init; select the exact module child.
        crash = """import os,signal
from pathlib import Path
matches=[]
for path in Path("/proc").glob("[0-9]*/cmdline"):
    try:
        args=path.read_bytes().split(b"\\0")
    except OSError:
        continue
    if args[1:3]==[b"-m",b"media_worker"]:
        matches.append(int(path.parent.name))
assert len(matches)==1
os.kill(matches[0],signal.SIGKILL)"""
        command(["docker", "exec", cid, "python", "-c", crash], expected=(0, 137))
        deadline = time.monotonic() + 70
        while time.monotonic() < deadline:
            state = json.loads(command(["docker", "inspect", cid]))[0]
            if (
                state["RestartCount"] >= 1
                and state["State"].get("Health", {}).get("Status") == "healthy"
            ):
                break
            time.sleep(1)
        else:
            raise AssertionError("worker did not restart healthy")
        report["automatic_restart_count"] = state["RestartCount"]
        command(
            [
                "docker",
                "exec",
                cid,
                "python",
                "-c",
                "from pathlib import Path; assert not Path('/tmp/worker-isolation-proof').exists()",
            ]
        )
        report["tmpfs_cleared_after_restart"] = True
        command(COMPOSE + ["stop", "--timeout", "30", "worker"])
        stopped = json.loads(command(["docker", "inspect", cid]))[0]["State"]
        assert not stopped["Running"] and stopped["ExitCode"] == 0
        report["sigterm_exit_code"] = stopped["ExitCode"]
        report["status"] = "passed"
    finally:
        command(COMPOSE + ["down", "--timeout", "30"])
        remaining = command(
            ["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={PROJECT}"]
        )
        assert not remaining
        report["verification_containers_removed"] = True
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
