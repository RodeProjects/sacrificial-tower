from __future__ import annotations

import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Sequence


@dataclass(frozen=True, slots=True)
class ProcessOutcome:
    command: tuple[str, ...]
    return_code: int | None
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool = False
    cancelled: bool = False


def isolated_slicer_environment(root: str | Path) -> dict[str, str]:
    """Redirect slicer user data, caches and temporary files to a throwaway root."""

    isolation_root = Path(root).resolve()
    roaming = isolation_root / "AppData" / "Roaming"
    local = isolation_root / "AppData" / "Local"
    home = isolation_root / "Home"
    temporary = isolation_root / "Temp"
    xdg_config = isolation_root / "xdg" / "config"
    xdg_cache = isolation_root / "xdg" / "cache"
    xdg_data = isolation_root / "xdg" / "data"
    for path in (
        roaming,
        local,
        home,
        temporary,
        xdg_config,
        xdg_cache,
        xdg_data,
    ):
        path.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "APPDATA": str(roaming),
            "LOCALAPPDATA": str(local),
            "HOME": str(home),
            "USERPROFILE": str(home),
            "TEMP": str(temporary),
            "TMP": str(temporary),
            "XDG_CONFIG_HOME": str(xdg_config),
            "XDG_CACHE_HOME": str(xdg_cache),
            "XDG_DATA_HOME": str(xdg_data),
            "COOLING_TOWER_SLICER_ISOLATED": "1",
        }
    )
    return environment


class SecureSlicerProcessRunner:
    """Run a slicer without a shell and with timeout/cancellation support."""

    def run(
        self,
        executable: str | Path,
        arguments: Sequence[str | Path],
        *,
        working_directory: str | Path,
        timeout_s: float,
        cancellation_event: Event | None = None,
    ) -> ProcessOutcome:
        executable_path = Path(executable).expanduser().resolve()
        if not executable_path.is_file():
            raise FileNotFoundError(f"Slicer executable not found: {executable_path}")
        if timeout_s <= 0:
            raise ValueError("Process timeout must be greater than zero.")

        working_path = Path(working_directory).expanduser().resolve()
        working_path.mkdir(parents=True, exist_ok=True)
        command = (str(executable_path), *(str(value) for value in arguments))
        creation_flags = 0
        if os.name == "nt":
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        started = time.monotonic()
        with tempfile.TemporaryDirectory(
            prefix="cooling_tower_slicer_environment_"
        ) as isolated_root:
            process = subprocess.Popen(
                command,
                cwd=str(working_path),
                env=isolated_slicer_environment(isolated_root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                creationflags=creation_flags,
            )
            stdout = ""
            stderr = ""
            timed_out = False
            cancelled = False
            while True:
                if cancellation_event is not None and cancellation_event.is_set():
                    cancelled = True
                    self._stop_process(process)
                    stdout, stderr = process.communicate()
                    break
                remaining = timeout_s - (time.monotonic() - started)
                if remaining <= 0:
                    timed_out = True
                    self._stop_process(process)
                    stdout, stderr = process.communicate()
                    break
                try:
                    stdout, stderr = process.communicate(timeout=min(0.1, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue

        return ProcessOutcome(
            command=command,
            return_code=process.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_s=max(0.0, time.monotonic() - started),
            timed_out=timed_out,
            cancelled=cancelled,
        )

    @staticmethod
    def _stop_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            try:
                subprocess.run(
                    (
                        "taskkill.exe",
                        "/PID",
                        str(process.pid),
                        "/T",
                        "/F",
                    ),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3.0,
                    shell=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
            if process.poll() is not None:
                return
        process.terminate()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2.0)
