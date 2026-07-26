from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cooling_tower.services.migration_service import MigrationService


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Move legacy flat output files into migrated_legacy."
    )
    parser.add_argument(
        "--output-root",
        default=str(PROJECT_ROOT / "output"),
        help="Existing output directory to migrate.",
    )
    arguments = parser.parse_args()
    result = MigrationService(arguments.output_root).migrate_flat_output()
    print(f"Moved files: {len(result.moved_files)}")
    print(f"Migration report: {result.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
