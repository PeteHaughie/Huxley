from __future__ import annotations
import os
import sys
import time
import signal
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from harness.config import MONSTER_HOME

APFELD_PORT = int(os.environ.get("APFELD_PORT", "11434"))
PID_PATH = MONSTER_HOME / "apfeld.pid"
LOG_PATH = MONSTER_HOME / "apfeld.log"


def _apfel_url(path: str = "/v1/models") -> str:
    return f"http://127.0.0.1:{APFELD_PORT}{path}"


def is_apfel_running() -> bool:
    if not PID_PATH.exists():
        return False
    try:
        pid = int(PID_PATH.read_text().strip())
        os.kill(pid, 0)
        resp = urllib.request.urlopen(_apfel_url(), timeout=2)
        return True
    except (ProcessLookupError, ValueError, OSError, urllib.error.URLError):
        PID_PATH.unlink(missing_ok=True)
        return False


def is_apfel_alive() -> bool:
    try:
        urllib.request.urlopen(_apfel_url(), timeout=2)
        return True
    except (urllib.error.URLError, ConnectionError, OSError):
        return False


def ensure_apfel() -> bool:
    if is_apfel_alive():
        if PID_PATH.exists():
            return True
        PID_PATH.unlink(missing_ok=True)
        return True
    if PID_PATH.exists():
        PID_PATH.unlink(missing_ok=True)
    cmd = ["apfel", "--serve"]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=open(LOG_PATH, "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except FileNotFoundError:
        print("γ|apfeld|not_found|apfel binary not on PATH", flush=True)
        return False
    PID_PATH.write_text(str(proc.pid))
    deadline = time.time() + 15
    while time.time() < deadline:
        if is_apfel_alive():
            print(f"γ|apfeld|start|{proc.pid}", flush=True)
            return True
        time.sleep(0.5)
    print("γ|apfeld|start_timeout|apfel did not respond within 15s", flush=True)
    return False


def stop_apfel() -> bool:
    if not PID_PATH.exists():
        return False
    try:
        pid = int(PID_PATH.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
                time.sleep(0.3)
            except ProcessLookupError:
                break
        PID_PATH.unlink(missing_ok=True)
        print(f"γ|apfeld|stop|{pid}", flush=True)
        return True
    except (ProcessLookupError, ValueError, OSError):
        PID_PATH.unlink(missing_ok=True)
        return False
