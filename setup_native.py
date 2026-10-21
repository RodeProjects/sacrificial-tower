from __future__ import annotations

import os
from pathlib import Path

from setuptools import Extension, setup


ROOT = Path(__file__).resolve().parent
NATIVE_COMPILE_ARGS = (
    ["/O2", "/std:c++17", "/fp:strict", "/EHsc"]
    if os.name == "nt"
    else ["-O3", "-std=c++17", "-fno-fast-math"]
)


def _windows_sdk_paths() -> tuple[list[str], list[str]]:
    """Find the newest installed Windows SDK without relying on VS shell state."""
    if os.name != "nt":
        return [], []

    kits_root = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10"
    include_root = kits_root / "Include"
    if not include_root.is_dir():
        return [], []

    versions = sorted(
        (
            candidate
            for candidate in include_root.iterdir()
            if (candidate / "ucrt" / "io.h").is_file()
            and (candidate / "um" / "Windows.h").is_file()
        ),
        key=lambda path: tuple(int(part) for part in path.name.split(".") if part.isdigit()),
        reverse=True,
    )
    if not versions:
        return [], []

    version = versions[0].name
    include_dirs = [
        str(include_root / version / component)
        for component in ("ucrt", "shared", "um", "winrt", "cppwinrt")
        if (include_root / version / component).is_dir()
    ]
    library_root = kits_root / "Lib" / version
    library_dirs = [
        str(library_root / component / "x64")
        for component in ("ucrt", "um")
        if (library_root / component / "x64").is_dir()
    ]
    return include_dirs, library_dirs


SDK_INCLUDE_DIRS, SDK_LIBRARY_DIRS = _windows_sdk_paths()


def _prepare_standalone_msvc_environment() -> tuple[list[str], list[str]]:
    """Make native builds work outside a Visual Studio Developer Prompt."""
    if os.name != "nt":
        return [], []

    visual_studio_root = Path(
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    ) / "Microsoft Visual Studio"
    compiler_candidates = sorted(
        visual_studio_root.glob("*/*/VC/Tools/MSVC/*/bin/Hostx64/x64/cl.exe"),
        reverse=True,
    )
    if not compiler_candidates:
        return [], []

    compiler = compiler_candidates[0]
    tool_root = compiler.parents[3]
    vc_include = tool_root / "include"
    vc_library = tool_root / "lib" / "x64"
    include_dirs = [str(vc_include)] if vc_include.is_dir() else []
    library_dirs = [str(vc_library)] if vc_library.is_dir() else []

    tool_paths = [str(compiler.parent)]
    if SDK_LIBRARY_DIRS:
        sdk_version = Path(SDK_LIBRARY_DIRS[0]).parents[1].name
        sdk_bin = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin" / sdk_version / "x64"
        if sdk_bin.is_dir():
            tool_paths.append(str(sdk_bin))
    os.environ["PATH"] = os.pathsep.join(tool_paths + [os.environ.get("PATH", "")])
    os.environ["INCLUDE"] = os.pathsep.join(include_dirs + SDK_INCLUDE_DIRS)
    os.environ["LIB"] = os.pathsep.join(library_dirs + SDK_LIBRARY_DIRS)
    os.environ["DISTUTILS_USE_SDK"] = "1"
    os.environ["MSSdk"] = "1"
    return include_dirs, library_dirs


VC_INCLUDE_DIRS, VC_LIBRARY_DIRS = _prepare_standalone_msvc_environment()


setup(
    name="sacrificial-tower-native",
    version="1.0.0",
    license_expression="Apache-2.0",
    license_files=["LICENSE.md", "NOTICE"],
    ext_modules=[
        Extension(
            "cooling_tower._native_timing",
            sources=[
                str(ROOT / "native" / "native_timing.cpp"),
                str(ROOT / "native" / "native_analysis.cpp"),
            ],
            depends=[str(path) for path in sorted((ROOT / "native").glob("*.hpp"))],
            include_dirs=(
                [str(ROOT / "native")]
                + VC_INCLUDE_DIRS
                + SDK_INCLUDE_DIRS
            ),
            library_dirs=VC_LIBRARY_DIRS + SDK_LIBRARY_DIRS,
            language="c++",
            extra_compile_args=NATIVE_COMPILE_ARGS,
        ),
    ],
    package_dir={"": "src"},
)
