"""Export resolved legal texts without publishing anything or accessing the network."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cooling_tower.legal_documents import export_legal_documents


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/legal-public")
    args = parser.parse_args()
    export_legal_documents(args.output, root=ROOT)
    print(f"Rechtstexte ohne Vorlagenfelder erstellt: {args.output.resolve()}")
