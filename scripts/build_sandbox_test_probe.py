"""Build the neutral Windows boundary payload outside application packaging."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output.resolve()
    if output.exists() or not output.parent.is_dir():
        parser.error('Use a new output file in an existing own test directory.')
    # Reuse the application's SDK discovery in this isolated build subprocess.
    from setup_native import VC_INCLUDE_DIRS, SDK_INCLUDE_DIRS, VC_LIBRARY_DIRS, SDK_LIBRARY_DIRS
    from setuptools._distutils.ccompiler import new_compiler
    compiler = new_compiler()
    compiler.initialize()
    objects = compiler.compile([str(ROOT / 'tests' / 'windows_sandbox_probe.c')],
        output_dir=str(output.parent / 'objects'), include_dirs=VC_INCLUDE_DIRS + SDK_INCLUDE_DIRS,
        extra_postargs=['/O2', '/W4'])
    compiler.link_shared_object(objects, str(output), libraries=['advapi32'],
        library_dirs=VC_LIBRARY_DIRS + SDK_LIBRARY_DIRS)


if __name__ == '__main__':
    main()
