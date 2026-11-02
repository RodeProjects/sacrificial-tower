"""Stage native slicer inputs and supervise the trusted LPAC broker."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from threading import Event
from typing import Mapping, Sequence

from cooling_tower.protected_io import OwnedWorkspace, UnsafeWorkspaceError, read_locked, require_owned_workspace
from cooling_tower.slicers.process import ProcessOutcome, ProcessRequest
from cooling_tower.slicers.windows_lpac import LpacProfile, SandboxUnavailableError


def native_host_path() -> Path:
    return Path(__file__).with_name('_native_slicer_host.exe')


def _cancelled(event: Event | None) -> None:
    if event is not None and event.is_set():
        raise InterruptedError("Der Slicerauftrag wurde abgebrochen.")


def _clone_tree(source: Path, target: Path, event: Event | None = None) -> None:
    """Copy bytes, not ACLs, attributes, junctions or hardlink relationships."""
    target.mkdir()
    pending = [(source, target)]
    file_count = 0
    total = 0
    while pending:
        original, copy = pending.pop()
        before = original.stat()
        entries = tuple(original.iterdir())
        for entry in entries:
            _cancelled(event)
            info = entry.lstat()
            if info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise SandboxUnavailableError("Eine Verknüpfung darf nicht in den Slicerbereich übernommen werden.")
            destination = copy / entry.name
            if entry.is_dir():
                destination.mkdir()
                pending.append((entry, destination))
            elif stat.S_ISREG(info.st_mode):
                file_count += 1
                total += info.st_size
                if file_count > 100_000 or total > 4 * 1024**3:
                    raise SandboxUnavailableError("Die Slicereingaben überschreiten die Ressourcengrenze.")
                with read_locked(entry) as stream, destination.open("xb") as output:
                    captured = os.fstat(stream.fileno())
                    if (captured.st_dev, captured.st_ino, captured.st_size, captured.st_mtime_ns) != (
                        info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                    ):
                        raise SandboxUnavailableError("Eine Slicereingabe wurde während der Übernahme ersetzt.")
                    copied_hash = hashlib.sha256()
                    while block := stream.read(1024 * 1024):
                        _cancelled(event)
                        copied_hash.update(block)
                        output.write(block)
                with destination.open("rb") as check:
                    if hashlib.file_digest(check, "sha256").digest() != copied_hash.digest():
                        raise SandboxUnavailableError("Eine Slicereingabe konnte nicht fehlerfrei kopiert werden.")
            else:
                raise SandboxUnavailableError("Eine Slicereingabe ist keine reguläre Datei.")
        after = original.stat()
        if (before.st_dev, before.st_ino, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_mtime_ns):
            raise SandboxUnavailableError("Ein Eingabeverzeichnis wurde während der Übernahme verändert.")


def _mapped_arguments(arguments: Sequence[str | Path], source: Path, target: Path) -> tuple[str, ...]:
    # Options may hold semicolon-separated profile paths. Do not use a shell
    # or split those option values into independently executable text.
    pattern = re.compile(re.escape(str(source)), re.IGNORECASE)
    return tuple(pattern.sub(lambda _: str(target), str(value)) for value in arguments)


def _publish(staged: Path, destination: OwnedWorkspace) -> None:
    from cooling_tower.slicers.windows_lpac import _assert_plain_tree
    _assert_plain_tree(staged)
    destination.assert_owned()
    for path in staged.rglob("*"):
        relative = path.relative_to(staged)
        target = destination.child(relative)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if target.exists():
            with path.open("rb") as new, target.open("rb") as old:
                if hashlib.file_digest(new, "sha256").digest() == hashlib.file_digest(old, "sha256").digest():
                    continue
        # Destination is owned scratch, not a user export. A sibling temporary
        # file prevents a failed copy from truncating a previous valid result.
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.child(relative.with_name(relative.name + ".publish.tmp"))
        created = False
        try:
            with path.open("rb") as source, temporary.open("xb") as output:
                created = True
                while block := source.read(1024 * 1024):
                    output.write(block)
            os.replace(temporary, target)
        finally:
            if created:
                temporary.unlink(missing_ok=True)


class WindowsProtectedSlicerProcessRunner:
    """Keep existing event-driven transport; restrict the actual slicer in LPAC."""

    def __init__(self, transport, *, mirror_runtime: bool = True, adapter_id: str | None = None) -> None:
        self.transport = transport
        self.backend_name = transport.backend_name
        self.mirror_runtime = mirror_runtime
        self.adapter_id = adapter_id

    def run(self, executable: str | Path, arguments: Sequence[str | Path], *,
            working_directory: str | Path, timeout_s: float, cancellation_event: Event | None = None,
            diagnostics_directory: str | Path | None = None, adapter_id: str | None = None,
            product_name: str | None = None, purpose: str | None = None,
            calibration_round: int | None = None, environment: Mapping[str, str] | None = None,
            state_callback=None) -> ProcessOutcome:
        original = Path(executable).resolve(strict=True)
        if not original.is_file():
            raise FileNotFoundError(original)
        owned = require_owned_workspace(working_directory)
        if timeout_s <= 0:
            raise ValueError("Process timeout must be greater than zero.")
        native_arguments = tuple(str(value) for value in arguments)
        selected_adapter = adapter_id or self.adapter_id
        # The native Windows launchers otherwise probe the hardware driver,
        # which can require writing its shared cache outside the job. Use their
        # existing CLI switches; no global graphics setting is changed.
        if selected_adapter == "prusa_slicer" and "--sw-renderer" not in native_arguments:
            native_arguments = ("--sw-renderer", *native_arguments)
        command = (str(original), *native_arguments)
        try:
            _cancelled(cancellation_event)
            # Bambu canonicalizes every executable-path ancestor. An LPAC must
            # be able to read those ancestors without granting rights to any
            # original directory. The OS temporary directory provides that
            # public ancestry; only a freshly created private child is changed.
            stage_parent = Path(os.environ["SystemRoot"]) / "Temp" if selected_adapter in {"bambu_studio", "prusa_slicer"} else None
            with OwnedWorkspace(prefix="st_", parent=stage_parent) as stage, LpacProfile() as profile:
                work = stage.child("w")
                _clone_tree(owned.path, work, cancellation_event)
                if self.mirror_runtime:
                    runtime = stage.child("s")
                    _clone_tree(original.parent, runtime, cancellation_event)
                    native_executable = runtime / original.name
                    if selected_adapter == "bambu_studio":
                        # This launcher recognizes --sw-renderer, but forwards
                        # it to a CLI parser that rejects it. Let the ordinary
                        # Windows DLL search select the *already bundled* Mesa
                        # library in our private program copy instead.
                        mesa = runtime / "mesa" / "opengl32.dll"
                        local_opengl = runtime / "opengl32.dll"
                        if not mesa.is_file() or local_opengl.exists():
                            raise SandboxUnavailableError("Die vorhandene Bambu-Softwaregrafik kann nicht sicher bereitgestellt werden.")
                        with mesa.open("rb") as source, local_opengl.open("xb") as target:
                            while block := source.read(1024 * 1024):
                                target.write(block)
                    engines = {
                        'anycubic_slicer_next': 'AnycubicSlicer.dll',
                        'bambu_studio': 'BambuStudio.dll',
                        'prusa_slicer': 'PrusaSlicer.dll',
                        'orca_slicer': 'OrcaSlicer.dll',
                    }
                    if selected_adapter not in engines or not (runtime / engines[selected_adapter]).is_file():
                        raise SandboxUnavailableError('Der geschützte native CLI-Einstieg dieser Slicerinstallation fehlt.')
                    host = native_host_path()
                    if not host.is_file():
                        raise SandboxUnavailableError("Der geschützte native Sliceraufruf fehlt. Native Anwendungskomponenten neu bauen.")
                    local_host = runtime / "st-slicer-host.exe"
                    with read_locked(host) as source, local_host.open("xb") as target:
                        while block := source.read(1024 * 1024):
                            target.write(block)
                    native_arguments = (str(native_executable), *native_arguments)
                    native_executable = local_host
                else:
                    # Only the small Windows console utility is used by the
                    # neutral OS-boundary tests; never allow an arbitrary
                    # unmirrored application through this testing facility.
                    permitted = Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"
                    if original != permitted.resolve():
                        raise SandboxUnavailableError("Diese native Testdatei ist nicht freigegeben.")
                    native_executable = original
                root_info = stage.path.stat()
                spec = stage.child("request.json")
                spec.write_text(json.dumps({"root": str(stage.path),
                    "identity": [root_info.st_dev, root_info.st_ino],
                    "executable": str(native_executable),
                    "profile_name": profile.name,
                    "console_probe": not self.mirror_runtime,
                    "native_host": self.mirror_runtime,
                    "software_renderer": selected_adapter == "bambu_studio",
                    "arguments": _mapped_arguments(native_arguments, owned.path, work),
                    "timeout_s": timeout_s}), encoding="utf-8")
                broker = Path(__file__).with_name("sandbox_broker.py")
                if getattr(sys, "frozen", False):
                    broker_arguments = ("--slicer-sandbox", str(spec))
                else:
                    broker_arguments = ("-I", "-X", "utf8", str(broker), str(spec))
                outcome = self.transport.run(sys.executable, broker_arguments,
                    working_directory=stage.path, timeout_s=timeout_s,
                    cancellation_event=cancellation_event, diagnostics_directory=diagnostics_directory,
                    adapter_id=adapter_id, product_name=product_name, purpose=purpose,
                    calibration_round=calibration_round, environment=environment, state_callback=state_callback)
                state_path = stage.child("native-state.json")
                state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
                if state.get('timed_out'):
                    outcome = replace(outcome, timed_out=True)
                # The parent, rather than the cancellable broker, owns profile
                # cleanup. A failed cleanup prevents publication and success.
                profile.close()
                if outcome.return_code == 0 and not outcome.cancelled and not outcome.timed_out:
                    if (not state.get("lpac") or not state.get("job_assigned")
                            or not state.get('job_stopped') or state.get('exit_code') != 0
                            or (self.mirror_runtime and not state.get('bootstrap_template_stopped'))
                            or not stage.child('broker-stopped.json').is_file()):
                        raise SandboxUnavailableError("Der sichere Slicerlauf wurde nicht vollständig bestätigt.")
                    _publish(work, owned)
                return replace(outcome, command=command, process_id=state.get("pid", outcome.process_id))
        except InterruptedError:
            return ProcessOutcome(command, None, "", "", 0.0, cancelled=True, backend=self.backend_name)

    def run_request(self, request: ProcessRequest) -> ProcessOutcome:
        return self.run(request.executable, request.arguments,
            working_directory=request.working_directory, timeout_s=request.timeout_s,
            cancellation_event=request.cancellation_event, diagnostics_directory=request.diagnostics_directory,
            adapter_id=request.adapter_id, product_name=request.product_name, purpose=request.purpose,
            calibration_round=request.calibration_round, environment=request.environment, state_callback=request.state_callback)
