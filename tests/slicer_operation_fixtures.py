"""Picklable child fixtures for real process failure and cancellation tests."""
import os
import subprocess
import sys
import time
from pathlib import Path


def return_value(value):
    return value


def raise_empty_error(_payload):
    raise RuntimeError()


def crash_process(_payload):
    os._exit(17)


def hang_process(marker):
    if marker:
        Path(marker).write_text(str(os.getpid()), encoding="ascii")
    while True:
        time.sleep(1)


def hang_with_descendant(marker):
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    Path(marker).write_text(str(child.pid), encoding="ascii")
    while True:
        time.sleep(1)
