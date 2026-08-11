from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


MAIN_BRANCH = "main"
MAIN_REF = f"refs/heads/{MAIN_BRANCH}"
TESTS_WORKFLOW = "tests.yml"
GITHUB_API_VERSION = "2022-11-28"
_COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


class ReleaseCiVerificationError(RuntimeError):
    """Raised when a release is not backed by successful main CI."""


def _validated_repository(repository: str) -> tuple[str, str]:
    parts = repository.split("/")
    if len(parts) != 2 or not all(parts):
        raise ReleaseCiVerificationError(
            "Das GitHub-Repository muss im Format owner/name angegeben werden."
        )
    return parts[0], parts[1]


def _validated_commit_sha(commit_sha: str) -> str:
    if not _COMMIT_SHA_PATTERN.fullmatch(commit_sha):
        raise ReleaseCiVerificationError(
            "Der Release-Commit muss als vollständige 40-stellige SHA vorliegen."
        )
    return commit_sha.lower()


def build_workflow_runs_url(repository: str, commit_sha: str) -> str:
    owner, name = _validated_repository(repository)
    expected_sha = _validated_commit_sha(commit_sha)
    query = urlencode(
        {
            "branch": MAIN_BRANCH,
            "event": "push",
            "head_sha": expected_sha,
            "status": "success",
            "per_page": 10,
        }
    )
    return (
        "https://api.github.com/repos/"
        f"{quote(owner, safe='')}/{quote(name, safe='')}/actions/workflows/"
        f"{quote(TESTS_WORKFLOW, safe='')}/runs?{query}"
    )


def validate_release_ref(ref: str) -> str:
    if ref != MAIN_REF:
        raise ReleaseCiVerificationError(
            f"Release-Builds sind ausschließlich von {MAIN_REF} erlaubt."
        )
    return ref


def validate_successful_main_run(
    payload: Mapping[str, Any], commit_sha: str
) -> Mapping[str, Any]:
    expected_sha = _validated_commit_sha(commit_sha)
    runs = payload.get("workflow_runs")
    if not isinstance(runs, list):
        raise ReleaseCiVerificationError(
            "Die GitHub-Antwort enthält keine gültige Workflow-Liste."
        )

    for candidate in runs:
        if not isinstance(candidate, Mapping):
            continue
        if (
            str(candidate.get("head_sha", "")).lower() == expected_sha
            and candidate.get("head_branch") == MAIN_BRANCH
            and candidate.get("event") == "push"
            and candidate.get("status") == "completed"
            and candidate.get("conclusion") == "success"
        ):
            return candidate

    raise ReleaseCiVerificationError(
        "Für den exakten Release-Commit wurde kein erfolgreich abgeschlossener "
        "Tests-Lauf auf main gefunden."
    )


def fetch_successful_main_run(
    repository: str,
    commit_sha: str,
    token: str,
) -> Mapping[str, Any]:
    if not token:
        raise ReleaseCiVerificationError(
            "GITHUB_TOKEN fehlt für die Prüfung des Tests-Workflows."
        )
    request = Request(
        build_workflow_runs_url(repository, commit_sha),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "Sacrificial-Tower-Release-CI-Verification",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ReleaseCiVerificationError(
            f"Der Tests-Status konnte nicht sicher von GitHub gelesen werden: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise ReleaseCiVerificationError(
            "GitHub hat keinen gültigen JSON-Datensatz zurückgegeben."
        )
    return validate_successful_main_run(payload, commit_sha)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verlangt vor einem Release-Build einen erfolgreichen Tests-Lauf "
            "für exakt denselben Commit auf main."
        )
    )
    parser.add_argument("--repository", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--ref", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        validate_release_ref(args.ref)
        run = fetch_successful_main_run(
            args.repository,
            args.sha,
            os.environ.get("GITHUB_TOKEN", ""),
        )
    except ReleaseCiVerificationError as exc:
        print(f"Release-CI-Prüfung fehlgeschlagen: {exc}", file=sys.stderr)
        return 1

    run_id = run.get("id", "unbekannt")
    run_url = run.get("html_url", "")
    print(
        "Release-CI-Prüfung erfolgreich: "
        f"Tests-Lauf {run_id} bestätigt Commit {args.sha}."
    )
    if run_url:
        print(f"Tests-Lauf: {run_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
