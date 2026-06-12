"""Load the BGL sample into PostgreSQL.

Usage:
    python scripts/load_data.py
"""
import logging
from pathlib import Path

from app.db.loader import load_bgl_file

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

SAMPLE = Path(__file__).parent.parent / "data" / "samples" / "BGL_2k.log"


def main() -> None:
    if not SAMPLE.exists():
        raise SystemExit(
            f"Sample not found at {SAMPLE}. Run scripts/download_data.py first."
        )
    summary = load_bgl_file(SAMPLE)
    print(f"\nLoaded {summary['rows_loaded']} rows")
    print(f"Discovered {summary['templates_found']} templates")


if __name__ == "__main__":
    main()