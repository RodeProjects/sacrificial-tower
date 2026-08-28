"""Build and run the portable C++ analysis smoke test without CPython APIs."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from setuptools._distutils.ccompiler import new_compiler
from setuptools._distutils.sysconfig import customize_compiler


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native"


def _prepare_windows_compiler() -> None:
    if os.name != "nt":
        return
    program_files = Path(
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    )
    compiler_candidates = sorted(
        (program_files / "Microsoft Visual Studio").glob(
            "*/*/VC/Tools/MSVC/*/bin/Hostx64/x64/cl.exe"
        ),
        reverse=True,
    )
    sdk_include_root = program_files / "Windows Kits" / "10" / "Include"
    sdk_versions = sorted(
        (
            candidate
            for candidate in sdk_include_root.iterdir()
            if (candidate / "ucrt" / "io.h").is_file()
            and (candidate / "um" / "Windows.h").is_file()
        ),
        reverse=True,
    )
    if not compiler_candidates or not sdk_versions:
        raise RuntimeError("No standalone MSVC/Windows SDK toolchain found.")
    compiler = compiler_candidates[0]
    tool_root = compiler.parents[3]
    sdk_version = sdk_versions[0].name
    sdk_root = program_files / "Windows Kits" / "10"
    tool_paths = [str(compiler.parent)]
    sdk_bin = sdk_root / "bin" / sdk_version / "x64"
    if sdk_bin.is_dir():
        tool_paths.append(str(sdk_bin))
    include_dirs = [
        tool_root / "include",
        *(sdk_root / "Include" / sdk_version / item
          for item in ("ucrt", "shared", "um", "winrt", "cppwinrt")),
    ]
    library_dirs = [
        tool_root / "lib" / "x64",
        sdk_root / "Lib" / sdk_version / "ucrt" / "x64",
        sdk_root / "Lib" / sdk_version / "um" / "x64",
    ]
    os.environ["PATH"] = os.pathsep.join(
        [*tool_paths, os.environ.get("PATH", "")]
    )
    os.environ["INCLUDE"] = os.pathsep.join(
        str(path) for path in include_dirs if path.is_dir()
    )
    os.environ["LIB"] = os.pathsep.join(
        str(path) for path in library_dirs if path.is_dir()
    )
    os.environ["DISTUTILS_USE_SDK"] = "1"
    os.environ["MSSdk"] = "1"


def main() -> int:
    _prepare_windows_compiler()
    compiler = new_compiler()
    customize_compiler(compiler)
    with tempfile.TemporaryDirectory(
        prefix="cooling_tower_native_core_"
    ) as temporary:
        build = Path(temporary)
        compile_options = (
            ["/std:c++17", "/fp:strict", "/EHsc", "/W4"]
            if os.name == "nt"
            else [
                "-std=c++17",
                "-fno-fast-math",
                "-Wall",
                "-Wextra",
                "-Wpedantic",
            ]
        )
        objects = compiler.compile(
            [
                str(NATIVE / "native_analysis.cpp"),
                str(NATIVE / "tests" / "native_analysis_smoke.cpp"),
            ],
            output_dir=str(build),
            include_dirs=[str(NATIVE)],
            extra_postargs=compile_options,
        )
        executable = build / "native_analysis_smoke"
        compiler.link_executable(objects, str(executable))
        completed = subprocess.run(
            [str(executable)],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if completed.returncode != 0:
            if completed.stdout:
                print(completed.stdout, end="")
            if completed.stderr:
                print(completed.stderr, end="")
        return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
