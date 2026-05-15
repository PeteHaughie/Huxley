from __future__ import annotations
import os
import sys
import socket
import time
import signal
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from harness.config import MONSTER_HOME

PID_PATH = MONSTER_HOME / "boardd.pid"
PORT_PATH = MONSTER_HOME / "boardd.port"
LOG_PATH = MONSTER_HOME / "boardd.log"


def _find_free_port(start: int, max_attempts: int = 10) -> int:
    for port in range(start, start + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(f"no free ports found starting at {start}")


def _board_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/api/tasks"


def is_boardd_running() -> bool:
    if not PID_PATH.exists():
        return False
    try:
        pid = int(PID_PATH.read_text().strip())
        os.kill(pid, 0)
        port = int(PORT_PATH.read_text().strip()) if PORT_PATH.exists() else 8080
        urllib.request.urlopen(_board_url(port), timeout=2)
        return True
    except (ProcessLookupError, ValueError, OSError, urllib.error.URLError):
        PID_PATH.unlink(missing_ok=True)
        PORT_PATH.unlink(missing_ok=True)
        return False


def start_boardd(port: int = 8080) -> bool:
    if is_boardd_running():
        return False
    actual_port = _find_free_port(port)
    cmd = [sys.executable, "-m", "harness.board", str(actual_port)]
    proc = subprocess.Popen(
        cmd,
        stdout=open(LOG_PATH, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    PID_PATH.write_text(str(proc.pid))
    PORT_PATH.write_text(str(actual_port))
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            urllib.request.urlopen(_board_url(actual_port), timeout=1)
            print(f"γ|boardd|start|{proc.pid}|:{actual_port}", flush=True)
            return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.3)
    print(f"γ|boardd|start_timeout|port {actual_port} not responding", flush=True)
    return False


def stop_boardd() -> bool:
    if not PID_PATH.exists():
        return False
    try:
        pid = int(PID_PATH.read_text().strip())
        port = int(PORT_PATH.read_text().strip()) if PORT_PATH.exists() else 8080
        req = urllib.request.Request(f"http://127.0.0.1:{port}/shutdown", method="POST")
        try:
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            pass
        os.kill(pid, signal.SIGTERM)
        deadline = time.time() + 3
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
                time.sleep(0.2)
            except ProcessLookupError:
                break
        PID_PATH.unlink(missing_ok=True)
        PORT_PATH.unlink(missing_ok=True)
        print(f"γ|boardd|stop|{pid}", flush=True)
        return True
    except (ProcessLookupError, ValueError, OSError):
        PID_PATH.unlink(missing_ok=True)
        PORT_PATH.unlink(missing_ok=True)
        return False


def boardd_status() -> dict:
    running = is_boardd_running()
    result = {"running": running}
    if running:
        port = int(PORT_PATH.read_text().strip()) if PORT_PATH.exists() else 8080
        result["port"] = port
        pid = int(PID_PATH.read_text().strip()) if PID_PATH.exists() else None
        result["pid"] = pid
    return result
