"""Conservatively decide whether a Git diff requires the full test suite."""

from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import re
import subprocess


VERSION_PATH = "src/cooling_tower/version.py"
ZERO_SHA = "0" * 40
CI_GATE_PATHS = {
    ".github/workflows/tests.yml",
    "scripts/classify_ci_changes.py",
    "tests/test_ci_change_classifier.py",
}
ROOT_DOCUMENTATION = {
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "LICENSE.md",
    "NOTICE",
    "NOTICE.md",
    "README.md",
    "SECURITY.md",
}
VERSION_ASSIGNMENT = re.compile(
    r"^(?P<prefix>APP_VERSION[ \t]*=[ \t]*)"
    r"(?P<quote>['\"])(?P<version>[0-9]+\.[0-9]+\.[0-9]+)(?P=quote)"
    r"(?P<trailing>[ \t]*\r?)$",
    re.MULTILINE,
)


def _git(repository: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"git {' '.join(arguments)} failed")
    return result.stdout


def _changed_entries(repository: Path, base: str, head: str) -> list[tuple[str, str]]:
    raw = _git(
        repository,
        "diff",
        "--name-status",
        "--no-renames",
        "-z",
        base,
        head,
        "--",
    )
    fields = raw.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    if len(fields) % 2:
        raise RuntimeError("git returned an incomplete name-status record")

    entries: list[tuple[str, str]] = []
    for index in range(0, len(fields), 2):
        status = fields[index].decode("ascii")
        path = fields[index + 1].decode("utf-8")
        entries.append((status, path))
    return entries


def _is_documentation_or_rule(path: str) -> bool:
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or ".." in candidate.parts or "\\" in path:
        return False
    if candidate.name == "AGENTS.md":
        return True
    if len(candidate.parts) > 1 and candidate.parts[0] == "docs":
        return True
    return len(candidate.parts) == 1 and candidate.name in ROOT_DOCUMENTATION


def _read_blob(repository: Path, revision: str, path: str) -> str:
    return _git(repository, "show", f"{revision}:{path}").decode("utf-8")


def _version_tuple(match: re.Match[str]) -> tuple[int, int, int]:
    major, minor, patch = match.group("version").split(".")
    return int(major), int(minor), int(patch)


def _is_static_version_increment(repository: Path, base: str, head: str) -> bool:
    try:
        old_text = _read_blob(repository, base, VERSION_PATH)
        new_text = _read_blob(repository, head, VERSION_PATH)
    except (RuntimeError, UnicodeDecodeError):
        return False

    old_matches = list(VERSION_ASSIGNMENT.finditer(old_text))
    new_matches = list(VERSION_ASSIGNMENT.finditer(new_text))
    if len(old_matches) != 1 or len(new_matches) != 1:
        return False

    old_match = old_matches[0]
    new_match = new_matches[0]
    old_masked = (
        old_text[: old_match.start("version")]
        + "<APP_VERSION>"
        + old_text[old_match.end("version") :]
    )
    new_masked = (
        new_text[: new_match.start("version")]
        + "<APP_VERSION>"
        + new_text[new_match.end("version") :]
    )
    if old_masked != new_masked:
        return False

    old_version = _version_tuple(old_match)
    new_version = _version_tuple(new_match)
    return (
        new_version[:2] == old_version[:2]
        and new_version[2] == old_version[2] + 1
    )


def classify_range(repository: Path, base: str, head: str) -> tuple[bool, str]:
    """Return ``(full_tests_required, reason)`` for the selected Git range."""

    if not base or not head or base == ZERO_SHA:
        return True, "Kein sicher vergleichbarer Basis-Commit; Full Suite erforderlich."

    try:
        entries = _changed_entries(repository, base, head)
    except (RuntimeError, UnicodeDecodeError) as error:
        return True, f"Diff konnte nicht sicher klassifiziert werden: {error}"

    if not entries:
        return True, "Leerer oder nicht bestimmbarer Diff; Full Suite erforderlich."

    for status, path in entries:
        if status not in {"A", "D", "M"}:
            return True, f"Nicht administrativer Git-Status {status!r} für {path}."
        if path in CI_GATE_PATHS:
            return True, f"Änderung an einer CI-Gate-Datei: {path}."
        if _is_documentation_or_rule(path):
            continue
        if (
            path == VERSION_PATH
            and status == "M"
            and _is_static_version_increment(repository, base, head)
        ):
            continue
        return True, f"Ausführungsrelevante oder unklare Änderung: {path}."

    return False, "Der Diff enthält ausschließlich sicher administrative Änderungen."


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--github-output", type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    full_tests_required, reason = classify_range(
        arguments.repository.resolve(),
        arguments.base,
        arguments.head,
    )
    output_value = "true" if full_tests_required else "false"
    print(f"full-tests-required={output_value}")
    print(reason)
    if arguments.github_output is not None:
        with arguments.github_output.open("a", encoding="utf-8") as output:
            output.write(f"full-tests-required={output_value}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
