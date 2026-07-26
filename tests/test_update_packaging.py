from __future__ import annotations

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class UpdatePackagingTests(unittest.TestCase):
    def test_pyinstaller_bundle_contains_required_runtime_data(self) -> None:
        spec = (PROJECT_ROOT / "SacrificialTower.spec").read_text(
            encoding="utf-8"
        )
        self.assertIn("start_gui.pyw", spec)
        self.assertIn("default_settings.json", spec)
        self.assertIn("styles.qss", spec)
        self.assertIn('name="SacrificialTower"', spec)
        self.assertIn("console=False", spec)

    def test_installer_is_per_user_and_restarts_the_application(self) -> None:
        installer = (
            PROJECT_ROOT / "installer" / "SacrificialTower.iss"
        ).read_text(encoding="utf-8")
        self.assertIn("PrivilegesRequired=lowest", installer)
        self.assertIn(
            "DefaultDirName={localappdata}\\Programs\\SacrificialTower",
            installer,
        )
        self.assertIn("RestartApplications=yes", installer)
        self.assertIn(
            'Filename: "{app}\\SacrificialTower.exe"',
            installer,
        )
        self.assertIn('WorkingDir: "{app}"', installer)

    def test_packaged_resources_and_persistent_files_use_separate_roots(self) -> None:
        main_window = (
            PROJECT_ROOT / "src" / "cooling_tower" / "gui" / "main_window.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'RESOURCE_ROOT / "config" / "default_settings.json"',
            main_window,
        )
        self.assertIn(
            'INSTALL_ROOT / "config" / "user_settings.json"',
            main_window,
        )

    def test_workflow_builds_and_hashes_the_installer(self) -> None:
        workflow = (
            PROJECT_ROOT / ".github" / "workflows" / "build-update.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("python -m unittest discover -s tests -q", workflow)
        self.assertIn("pyinstaller --noconfirm --clean", workflow)
        self.assertIn("Inno Setup", workflow)
        self.assertIn("Get-FileHash", workflow)
        self.assertIn("actions/upload-artifact@v4", workflow)

    def test_publish_script_uses_local_gh_auth_and_public_channel(self) -> None:
        script = (
            PROJECT_ROOT / "scripts" / "publish_update.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("auth status", script)
        self.assertIn("RodeProjects/sacrificial-tower-updates", script)
        self.assertIn("update-metadata.json", script)
        self.assertNotIn("Authorization: Bearer", script)
        self.assertNotIn("personal_access_token", script.casefold())


if __name__ == "__main__":
    unittest.main()
