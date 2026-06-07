"""Download the BGL 2k sample log dataset from the Loghub GitHub repository.

This grabs a small (~200 KB) labeled subset so we can start working immediately.
The full BGL dataset (~700MB) can be downloaded later for the real eval runs.

Usage:
    python scripts/download_data.py
"""
import sys
import urllib.request
from pathlib import Path

# Loghub BGL 2k sample - small labeled subset, hosted in the official repo
BGL_2K_URL = (
    "https://raw.githubusercontent.com/logpai/loghub/master/BGL/BGL_2k.log"
)

DATA_DIR = Path(__file__).parent.parent / "data" / "samples"


def download_bgl_sample() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / "BGL_2k.log"

    if out_path.exists():
        print(f"[skip] Already exists: {out_path}")
        return

    print(f"[download] {BGL_2K_URL}")
    try:
        urllib.request.urlretrieve(BGL_2K_URL, out_path)
    except Exception as e:
        print(f"[error] Download failed: {e}", file=sys.stderr)
        sys.exit(1)

    size_kb = out_path.stat().st_size / 1024
    print(f"[done] Saved to {out_path} ({size_kb:.1f} KB)")

    # Quick peek at the data
    with open(out_path, "r") as f:
        lines = [next(f) for _ in range(3)]
    print("\n[preview] First 3 lines:")
    for line in lines:
        print(f"  {line.rstrip()}")


if __name__ == "__main__":
    download_bgl_sample()
