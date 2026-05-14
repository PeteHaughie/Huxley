import os
import json
import sys
import subprocess
import time
import signal
import urllib.request
import urllib.error
from pathlib import Path
from harness.config import MONSTER_HOME

PID_PATH = MONSTER_HOME / "monsterd.pid"
LOG_PATH = MONSTER_HOME / "monsterd.log"
DAEMON_PORT = int(os.environ.get("MONSTERD_PORT", "8083"))


def _daemon_url(path: str) -> str:
    return f"http://127.0.0.1:{DAEMON_PORT}{path}"


def is_running() -> bool:
    if not PID_PATH.exists():
        return False
    try:
        pid = int(PID_PATH.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, ValueError, OSError):
        PID_PATH.unlink(missing_ok=True)
        return False


def start_daemon() -> bool:
    if is_running():
        return False
    cmd = [sys.executable, "-m", "harness.daemon"]
    proc = subprocess.Popen(
        cmd,
        stdout=open(LOG_PATH, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    PID_PATH.write_text(str(proc.pid))
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            urllib.request.urlopen(_daemon_url("/health"), timeout=1)
            return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.5)
    return False


def stop_daemon() -> bool:
    if not is_running():
        return False
    try:
        req = urllib.request.Request(_daemon_url("/v1/shutdown"), method="POST")
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass
    try:
        pid = int(PID_PATH.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        os.kill(pid, 0)
        time.sleep(1)
    except ProcessLookupError:
        pass
    PID_PATH.unlink(missing_ok=True)
    return True


def daemon_status() -> dict:
    running = is_running()
    result = {"running": running}
    if running:
        try:
            resp = urllib.request.urlopen(_daemon_url("/v1/status"), timeout=3)
            result.update(json.loads(resp.read()))
        except Exception as e:
            result["error"] = str(e)
    return result
