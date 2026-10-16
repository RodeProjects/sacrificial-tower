from __future__ import annotations

import io
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]

from scripts.verify_release_ci import (
    ReleaseCiVerificationError,
    build_workflow_runs_url,
    fetch_successful_main_run,
    validate_release_ref,
    validate_successful_main_run,
)


class UpdatePackagingTests(unittest.TestCase):
    def test_installer_replacement_supports_minor_and_major_boundaries(
        self,
    ) -> None:
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell is None:
            self.skipTest("PowerShell ist für den Installer-Test nicht verfügbar.")
        module = (
            PROJECT_ROOT / "scripts" / "InstallerReplacementVersion.psm1"
        )

        completed = subprocess.run(
            (
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                (
                    f"Import-Module '{module}'; "
                    "Get-OlderInstallerTestVersion -Version '0.5.1'; "
                    "Get-OlderInstallerTestVersion -Version '0.5.0'; "
                    "Get-OlderInstallerTestVersion -Version '1.0.0'; "
                    "try { "
                    "Get-OlderInstallerTestVersion -Version '0.0.0'; "
                    "exit 2 "
                    "} catch { $_.Exception.Message }"
                ),
            ),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output_lines = completed.stdout.splitlines()
        self.assertEqual(output_lines[:3], ["0.5.0", "0.4.0", "0.0.0"])
        self.assertIn("Version 0.0.0", output_lines[3])
        self.assertIn("Testversion", output_lines[3])

    def test_app_version_is_the_single_release_version_source(self) -> None:
        installer = (
            PROJECT_ROOT / "installer" / "SacrificialTower.iss"
        ).read_text(encoding="utf-8")
        workflow = (
            PROJECT_ROOT / ".github" / "workflows" / "build-update.yml"
        ).read_text(encoding="utf-8")
        spec = (PROJECT_ROOT / "SacrificialTower.spec").read_text(
            encoding="utf-8"
        )

        self.assertNotIn('#define AppVersion "0.0.0"', installer)
        self.assertIn("#error AppVersion muss", installer)
        self.assertIn(
            "from cooling_tower.version import APP_VERSION", workflow
        )
        self.assertIn('"/DAppVersion=$env:APP_VERSION"', workflow)
        self.assertIn('version_namespace["APP_VERSION"]', spec)

    def test_release_ci_query_is_limited_to_the_exact_main_commit(self) -> None:
        commit_sha = "a" * 40
        url = build_workflow_runs_url(
            "RodeProjects/sacrificial-tower", commit_sha
        )
        parsed = urlparse(url)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "api.github.com")
        self.assertEqual(
            parsed.path,
            (
                "/repos/RodeProjects/sacrificial-tower/actions/workflows/"
                "tests.yml/runs"
            ),
        )
        self.assertEqual(
            parse_qs(parsed.query),
            {
                "branch": ["main"],
                "event": ["push"],
                "head_sha": [commit_sha],
                "status": ["success"],
                "per_page": ["10"],
            },
        )

    def test_release_ci_accepts_only_completed_success_for_exact_commit(
        self,
    ) -> None:
        commit_sha = "b" * 40
        valid_run = {
            "id": 42,
            "head_sha": commit_sha,
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        }
        self.assertIs(
            validate_successful_main_run(
                {"workflow_runs": [valid_run]}, commit_sha
            ),
            valid_run,
        )

        invalid_variants = (
            {**valid_run, "head_sha": "c" * 40},
            {**valid_run, "head_branch": "feature"},
            {**valid_run, "event": "workflow_dispatch"},
            {**valid_run, "status": "in_progress"},
            {**valid_run, "conclusion": "failure"},
        )
        for invalid_run in invalid_variants:
            with self.subTest(invalid_run=invalid_run):
                with self.assertRaises(ReleaseCiVerificationError):
                    validate_successful_main_run(
                        {"workflow_runs": [invalid_run]}, commit_sha
                    )

    def test_release_ci_rejects_unsafe_inputs_before_network_access(
        self,
    ) -> None:
        commit_sha = "d" * 40
        self.assertEqual(
            validate_release_ref("refs/heads/main"), "refs/heads/main"
        )
        for invalid_ref in ("refs/heads/feature", "refs/tags/v0.5.3", "main"):
            with self.subTest(invalid_ref=invalid_ref):
                with self.assertRaises(ReleaseCiVerificationError):
                    validate_release_ref(invalid_ref)

        for repository, sha in (
            ("missing-owner", commit_sha),
            ("owner/", commit_sha),
            ("owner/repository", "short-sha"),
        ):
            with self.subTest(repository=repository, sha=sha):
                with self.assertRaises(ReleaseCiVerificationError):
                    build_workflow_runs_url(repository, sha)

        with self.assertRaises(ReleaseCiVerificationError):
            fetch_successful_main_run(
                "RodeProjects/sacrificial-tower", commit_sha, ""
            )

    def test_release_ci_fetch_uses_authenticated_github_request(self) -> None:
        commit_sha = "e" * 40
        valid_run = {
            "id": 84,
            "head_sha": commit_sha,
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        }
        response = io.BytesIO(
            json.dumps({"workflow_runs": [valid_run]}).encode("utf-8")
        )
        with patch(
            "scripts.verify_release_ci.urlopen", return_value=response
        ) as open_url:
            self.assertEqual(
                fetch_successful_main_run(
                    "RodeProjects/sacrificial-tower",
                    commit_sha,
                    "test-token",
                ),
                valid_run,
            )

        request = open_url.call_args.args[0]
        self.assertEqual(open_url.call_args.kwargs, {"timeout": 20})
        self.assertEqual(
            request.get_header("Authorization"), "Bearer test-token"
        )
        self.assertEqual(
            request.get_header("X-github-api-version"), "2022-11-28"
        )

    def test_pyinstaller_bundle_contains_required_runtime_data(self) -> None:
        spec = (PROJECT_ROOT / "SacrificialTower.spec").read_text(
            encoding="utf-8"
        )
        self.assertIn("start_gui.pyw", spec)
        self.assertIn("default_settings.json", spec)
        self.assertIn("distribution.json", spec)
        self.assertIn("styles.qss", spec)
        self.assertIn('name="SacrificialTower"', spec)
        self.assertIn("console=False", spec)
        self.assertIn("windows_version_info.txt", spec)
        self.assertIn("version=str(version_info_path)", spec)
        self.assertIn('"cooling_tower._native_timing"', spec)
        self.assertIn("native_timing_extensions", spec)
        self.assertIn('"assets" / "app.ico"', spec)
        self.assertIn("StringStruct(u'CompanyName', {provider_name!r})", spec)
        self.assertIn("config/legal_profile.json", spec)
        application = (
            PROJECT_ROOT / "src" / "cooling_tower" / "application.py"
        ).read_text(encoding="utf-8")
        self.assertIn("application.setWindowIcon", application)
        self.assertIn('"assets" / "app.ico"', application)

    def test_installer_is_per_user_and_restarts_the_application(self) -> None:
        installer = (
            PROJECT_ROOT / "installer" / "SacrificialTower.iss"
        ).read_text(encoding="utf-8")
        self.assertIn("PrivilegesRequired=lowest", installer)
        self.assertIn(
            "SetupIconFile=..\\src\\cooling_tower\\gui\\assets\\app.ico",
            installer,
        )
        self.assertIn(
            '#define DefaultInstallDir "{localappdata}\\Programs\\SacrificialTower"',
            installer,
        )
        self.assertIn("DefaultDirName={#DefaultInstallDir}", installer)
        self.assertIn("RestartApplications=yes", installer)
        self.assertIn(
            'Filename: "{app}\\SacrificialTower.exe"',
            installer,
        )
        self.assertIn('WorkingDir: "{app}"', installer)
        self.assertIn(
            'Description: "Sacrificial-Tower jetzt starten?"',
            installer,
        )
        self.assertIn("Flags: nowait postinstall skipifsilent", installer)
        self.assertIn(
            'Flags: nowait skipifnotsilent; Check: IsAutomaticUpdate',
            installer,
        )
        self.assertIn("HasCommandLineSwitch('SACRIFICIALTOWERUPDATE')", installer)
        self.assertNotIn(
            'Description: "Sacrificial Tower starten"; Flags: nowait',
            installer,
        )
        self.assertIn("VersionInfoVersion={#AppVersion}", installer)
        self.assertIn("OutputDir={#InstallerOutputDir}", installer)
        self.assertIn(
            "OutputBaseFilename={#InstallerOutputBaseFilename}",
            installer,
        )

    def test_uninstaller_preserves_data_unless_deletion_is_explicit(self) -> None:
        installer = (
            PROJECT_ROOT / "installer" / "SacrificialTower.iss"
        ).read_text(encoding="utf-8")

        self.assertIn("Uninstallable=yes", installer)
        self.assertIn("UninstallDisplayName=Sacrificial Tower", installer)
        self.assertIn('Filename: "{uninstallexe}"', installer)
        self.assertIn(
            '#define StandaloneUserDataDir '
            '"{localappdata}\\RodeProjects\\SacrificialTower\\standalone"',
            installer,
        )
        self.assertIn("HasCommandLineSwitch('DELETEUSERDATA')", installer)
        self.assertIn("HasCommandLineSwitch('VERYSILENT')", installer)
        self.assertIn("HasCommandLineSwitch('SUPPRESSMSGBOXES')", installer)
        self.assertIn("MB_YESNO or MB_DEFBUTTON2", installer)
        self.assertIn("IDNO) = IDYES", installer)
        self.assertIn("DelTree(UserDataRoot, True, True, True)", installer)
        self.assertIn("CurUninstallStep = usPostUninstall", installer)
        self.assertIn("CheckForMutexes('{#ApplicationMutexName}')", installer)
        self.assertIn('Type: dirifempty; Name: "{app}"', installer)
        self.assertNotIn('Type: filesandordirs; Name: "{app}"', installer)
        self.assertNotIn('Name: "{app}\\*"', installer)

        mutex_source = (
            PROJECT_ROOT / "src" / "cooling_tower" / "application_mutex.py"
        ).read_text(encoding="utf-8")
        mutex_name = (
            "SacrificialTower-Standalone-"
            "D47169C5-9DE6-46AF-A8C9-72A394CD2949"
        )
        self.assertIn(mutex_name, installer)
        self.assertIn(mutex_name, mutex_source)

    def test_installer_and_uninstaller_messages_are_german(self) -> None:
        installer = (
            PROJECT_ROOT / "installer" / "SacrificialTower.iss"
        ).read_text(encoding="utf-8")

        self.assertIn("[Languages]", installer)
        self.assertIn(
            'Name: "german"; MessagesFile: "compiler:Languages\\German.isl"',
            installer,
        )
        self.assertNotIn(
            "Daten anderer Sacrificial-Tower-Instanzen bleiben unangetastet.",
            installer,
        )

    def test_installer_handles_reinstall_and_downgrade_explicitly(self) -> None:
        installer = (
            PROJECT_ROOT / "installer" / "SacrificialTower.iss"
        ).read_text(encoding="utf-8")

        self.assertIn("ComparePackedVersion", installer)
        self.assertIn("Möchten Sie die Neuinstallation fortsetzen?", installer)
        self.assertIn(
            "derzeit installierte Version zuerst deinstalliert werden.",
            installer,
        )
        self.assertIn("MB_YESNOCANCEL or MB_DEFBUTTON2", installer)
        self.assertIn("Das Beibehalten wird empfohlen.", installer)
        self.assertIn("function PrepareToInstall", installer)
        self.assertIn("ExistingReplacementPending := True", installer)
        self.assertIn("RunExistingUninstaller", installer)
        self.assertIn("/VERYSILENT /SUPPRESSMSGBOXES /NORESTART", installer)

    def test_release_build_uses_free_signed_update_manifest(self) -> None:
        installer = (
            PROJECT_ROOT / "installer" / "SacrificialTower.iss"
        ).read_text(encoding="utf-8")
        workflow = (
            PROJECT_ROOT / ".github" / "workflows" / "build-update.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("SignTool=authenticode", installer)
        self.assertIn("SignedUninstaller=yes", installer)
        self.assertIn("Flags: ignoreversion signonce", installer)
        self.assertIn("UPDATE_MANIFEST_SIGNING_KEY_BASE64", workflow)
        self.assertIn("create_update_manifest.py", workflow)
        self.assertIn("release_kind", workflow)
        self.assertIn("Entwicklungsversion für Tests und Evaluation", workflow)
        self.assertIn("dist/installer/latest.json", workflow)
        self.assertNotIn("WINDOWS_SIGNING_CERTIFICATE_BASE64", workflow)
        self.assertNotIn("WINDOWS_SIGNING_CERTIFICATE_PASSWORD", workflow)
        self.assertNotIn("/DSignBuild=1", workflow)
        self.assertNotIn("Get-AuthenticodeSignature", workflow)

    def test_packaged_resources_and_persistent_files_use_separate_roots(self) -> None:
        main_window = (
            PROJECT_ROOT / "src" / "cooling_tower" / "gui" / "main_window.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'RESOURCE_ROOT / "config" / "default_settings.json"',
            main_window,
        )
        self.assertIn('user_config_root / "user_settings.json"', main_window)
        self.assertIn("resolve_user_data_root", main_window)
        self.assertIn("migrate_legacy_configuration", main_window)

    def test_workflow_builds_and_hashes_the_installer(self) -> None:
        workflow = (
            PROJECT_ROOT / ".github" / "workflows" / "build-update.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("actions: read", workflow)
        self.assertIn("scripts/verify_release_ci.py", workflow)
        self.assertIn("inputs.release_kind != 'development' || !inputs.allow_timed_out_ci", workflow)
        self.assertIn("inputs.release_kind == 'development' && inputs.allow_timed_out_ci", workflow)
        self.assertIn('--sha "${{ github.sha }}"', workflow)
        self.assertIn('--ref "${{ github.ref }}"', workflow)
        self.assertNotIn("python -m unittest discover -s tests -q", workflow)
        self.assertIn("pyinstaller --noconfirm --clean", workflow)
        self.assertIn("Inno Setup", workflow)
        self.assertIn("Get-FileHash", workflow)
        self.assertIn("actions/checkout@v5", workflow)
        self.assertIn("actions/setup-python@v6", workflow)
        self.assertIn("actions/upload-artifact@v5", workflow)
        self.assertIn("test_uninstaller.ps1", workflow)
        self.assertIn("test_installer_replacement.ps1", workflow)
        self.assertIn(
            "name: Windows-Installer für Sacrificial-Tower-Update bauen",
            workflow,
        )

    def test_publish_script_uses_local_gh_auth_and_public_channel(self) -> None:
        script = (
            PROJECT_ROOT / "scripts" / "publish_update.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("auth status", script)
        self.assertIn("RodeProjects/sacrificial-tower-updates", script)
        self.assertIn("update-metadata.json", script)
        self.assertIn("verify_update_manifest.py", script)
        self.assertIn("latest.json", script)
        self.assertNotIn("Get-AuthenticodeSignature", script)
        self.assertNotIn("signer_thumbprint", script)
        self.assertIn("Assert-NativeSuccess \"Der Build-Workflow\"", script)
        self.assertIn("Programmupdate-Kanal auf Version $version", script)
        self.assertIn("release delete $tag", script)
        self.assertIn("[switch]$DevelopmentRelease", script)
        self.assertIn("[switch]$AllowTimedOutCI", script)
        self.assertIn("$AllowTimedOutCI -and -not $DevelopmentRelease", script)
        self.assertIn('allow_timed_out_ci=$($AllowTimedOutCI.IsPresent.ToString().ToLowerInvariant())', script)
        self.assertIn("--development-release", script)
        self.assertIn('"--latest"', script)
        self.assertNotIn('"--prerelease"', script)
        self.assertIn("Sacrificial Tower $version (Entwicklungsversion)", script)
        self.assertIn('-f "release_kind=$releaseKind"', script)
        self.assertNotIn("Authorization: Bearer", script)
        self.assertNotIn("personal_access_token", script.casefold())

    def test_runtime_dependency_contains_manifest_signature_support(self) -> None:
        requirements = (PROJECT_ROOT / "requirements.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("cryptography>=49,<50", requirements)


if __name__ == "__main__":
    unittest.main()
