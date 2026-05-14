from __future__ import annotations
import os
import sys
import signal


def hot_reload():
    os.execv(sys.executable, [sys.executable] + sys.argv)


def register_reload_handler():
    signal.signal(signal.SIGHUP, lambda sig, frame: hot_reload())
