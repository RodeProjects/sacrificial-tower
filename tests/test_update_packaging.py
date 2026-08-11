from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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

        for current, expected in (
            ("0.5.1", "0.5.0"),
            ("0.5.0", "0.4.0"),
            ("1.0.0", "0.0.0"),
        ):
            with self.subTest(current=current):
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
                            f"Get-OlderInstallerTestVersion -Version '{current}'"
                        ),
                    ),
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(completed.stdout.strip(), expected)

        unsupported = subprocess.run(
            (
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                (
                    f"Import-Module '{module}'; "
                    "Get-OlderInstallerTestVersion -Version '0.0.0'"
                ),
            ),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        self.assertNotEqual(unsupported.returncode, 0)
        self.assertIn("Version 0.0.0", unsupported.stderr)
        self.assertIn("Testversion", unsupported.stderr)

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
        self.assertIn("StringStruct(u'CompanyName', u'RodeProjects')", spec)

    def test_installer_is_per_user_and_restarts_the_application(self) -> None:
        installer = (
            PROJECT_ROOT / "installer" / "SacrificialTower.iss"
        ).read_text(encoding="utf-8")
        self.assertIn("PrivilegesRequired=lowest", installer)
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
        self.assertIn("python -m unittest discover -s tests -q", workflow)
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
        self.assertNotIn("Authorization: Bearer", script)
        self.assertNotIn("personal_access_token", script.casefold())

    def test_runtime_dependency_contains_manifest_signature_support(self) -> None:
        requirements = (PROJECT_ROOT / "requirements.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("cryptography>=49,<50", requirements)


if __name__ == "__main__":
    unittest.main()
