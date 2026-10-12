from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.classify_ci_changes import classify_range


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "Kühlturm-Generator"
APP_SUBTITLE = "Erzeugt Opferobjekte passend zur gewünschten Layerzeit"


class CiChangeClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary_directory.name)
        self._git("init", "--initial-branch=main")
        self._git("config", "user.email", "tests@example.invalid")
        self._git("config", "user.name", "CI classifier tests")
        self._write("AGENTS.md", "# Regeln\n")
        self._write("docs/README.md", "# Dokumentation\n")
        self._write("src/cooling_tower/version.py", self._version_content("0.6.9"))
        self._write("src/cooling_tower/example.py", "VALUE = 1\n")
        self._write(".github/workflows/tests.yml", "name: Tests\n")
        self._write("scripts/classify_ci_changes.py", "# classifier\n")
        self._write("tests/test_example.py", "# test\n")
        self._write("tests/test_ci_change_classifier.py", "# classifier tests\n")
        self.base = self._commit("Basis")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _git(self, *arguments: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.repository), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return result.stdout.strip()

    def _write(self, relative_path: str, content: str) -> None:
        path = self.repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _version_content(
        version: str,
        *,
        app_name: str = APP_NAME,
        extra: str = "",
    ) -> str:
        return (
            '"""Application version information."""\n\n'
            f'APP_NAME = "{app_name}"\n'
            f'APP_SUBTITLE = "{APP_SUBTITLE}"\n'
            f'APP_VERSION = "{version}"\n'
            'APP_VERSION_LABEL = f"Version {APP_VERSION}"\n'
            f"{extra}"
        )

    def _commit(self, message: str) -> str:
        self._git("add", "--all")
        self._git("commit", "-m", message)
        return self._git("rev-parse", "HEAD")

    def _classify_head(self) -> tuple[bool, str]:
        head = self._commit("Änderung")
        return classify_range(self.repository, self.base, head)

    def test_rules_and_static_patch_increment_are_administrative(self) -> None:
        self._write("AGENTS.md", "# Überarbeitete Regeln\n")
        self._write("src/cooling_tower/version.py", self._version_content("0.6.10"))

        full_tests_required, _ = self._classify_head()

        self.assertFalse(full_tests_required)

    def test_documentation_only_is_administrative(self) -> None:
        self._write("docs/README.md", "# Neue Dokumentation\n")

        full_tests_required, _ = self._classify_head()

        self.assertFalse(full_tests_required)

    def test_rules_documentation_and_static_patch_increment_are_administrative(
        self,
    ) -> None:
        self._write("AGENTS.md", "# Überarbeitete Regeln\n")
        self._write("docs/README.md", "# Neue Dokumentation\n")
        self._write("src/cooling_tower/version.py", self._version_content("0.6.10"))

        full_tests_required, _ = self._classify_head()

        self.assertFalse(full_tests_required)

    def test_other_version_module_change_requires_full_suite(self) -> None:
        self._write(
            "src/cooling_tower/version.py",
            self._version_content("0.6.10", app_name="Anderer Name"),
        )

        full_tests_required, _ = self._classify_head()

        self.assertTrue(full_tests_required)

    def test_non_incrementing_version_change_requires_full_suite(self) -> None:
        self._write("src/cooling_tower/version.py", self._version_content("0.7.0"))

        full_tests_required, _ = self._classify_head()

        self.assertTrue(full_tests_required)

    def test_skipped_patch_version_requires_full_suite(self) -> None:
        self._write("src/cooling_tower/version.py", self._version_content("0.6.11"))

        full_tests_required, _ = self._classify_head()

        self.assertTrue(full_tests_required)

    def test_version_downgrade_requires_full_suite(self) -> None:
        self._write("src/cooling_tower/version.py", self._version_content("0.6.8"))

        full_tests_required, _ = self._classify_head()

        self.assertTrue(full_tests_required)

    def test_added_version_module_logic_requires_full_suite(self) -> None:
        self._write(
            "src/cooling_tower/version.py",
            self._version_content(
                "0.6.10",
                extra="\ndef version_tuple():\n    return (0, 6, 10)\n",
            ),
        )

        full_tests_required, _ = self._classify_head()

        self.assertTrue(full_tests_required)

    def test_code_change_requires_full_suite(self) -> None:
        self._write("src/cooling_tower/example.py", "VALUE = 2\n")

        full_tests_required, _ = self._classify_head()

        self.assertTrue(full_tests_required)

    def test_mixed_administrative_and_code_change_requires_full_suite(self) -> None:
        self._write("AGENTS.md", "# Überarbeitete Regeln\n")
        self._write("src/cooling_tower/example.py", "VALUE = 2\n")

        full_tests_required, _ = self._classify_head()

        self.assertTrue(full_tests_required)

    def test_workflow_change_requires_full_suite(self) -> None:
        self._write(".github/workflows/tests.yml", "# changed\n")

        full_tests_required, _ = self._classify_head()

        self.assertTrue(full_tests_required)

    def test_classifier_change_requires_full_suite(self) -> None:
        self._write("scripts/classify_ci_changes.py", "# changed\n")

        full_tests_required, _ = self._classify_head()

        self.assertTrue(full_tests_required)

    def test_classifier_test_change_requires_full_suite(self) -> None:
        self._write("tests/test_ci_change_classifier.py", "# changed\n")

        full_tests_required, _ = self._classify_head()

        self.assertTrue(full_tests_required)

    def test_test_change_requires_full_suite(self) -> None:
        self._write("tests/test_example.py", "# changed\n")

        full_tests_required, _ = self._classify_head()

        self.assertTrue(full_tests_required)

    def test_missing_base_fails_closed(self) -> None:
        full_tests_required, _ = classify_range(
            self.repository,
            "0" * 40,
            self.base,
        )

        self.assertTrue(full_tests_required)


class WorkflowDefinitionTests(unittest.TestCase):
    def test_classifier_safely_controls_the_full_windows_job(self) -> None:
        workflow = (PROJECT_ROOT / ".github/workflows/tests.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("classify:\n", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("scripts/classify_ci_changes.py", workflow)
        self.assertIn("gate-files-changed == 'true'", workflow)
        self.assertIn("steps.gate.outputs.gate-files-changed != 'true'", workflow)
        self.assertIn(".github/workflows/tests.yml", workflow)
        self.assertIn("tests/test_ci_change_classifier.py", workflow)
        self.assertIn("needs: classify", workflow)
        self.assertIn("always() && !cancelled()", workflow)
        self.assertIn("!cancelled()", workflow)
        self.assertIn("needs.classify.result != 'success'", workflow)
        self.assertIn(
            "needs.classify.outputs.full-tests-required != 'false'", workflow
        )
        self.assertIn("runs-on: windows-latest", workflow)
        self.assertIn('python-version: "3.13"', workflow)
        self.assertIn("python -m pip install --require-hashes -r requirements-windows.lock", workflow)
        self.assertIn("python setup_native.py build_ext --inplace", workflow)
        self.assertIn("python scripts/run_isolated_tests.py", workflow)


if __name__ == "__main__":
    unittest.main()
