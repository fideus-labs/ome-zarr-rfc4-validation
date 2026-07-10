#!/usr/bin/env python3
"""Fetch the RFC-4 sample data from the Hugging Face dataset repo.

The images live in Hugging Face, not in this git repo. This clones (or updates)
the HF repo into ./hf-data so the validator and conformance suite can run against
real data:

    python fetch_data.py
    python validate_rfc4.py --data-dir hf-data
"""
from __future__ import annotations

import os
import subprocess
import sys

HF_URL = "https://huggingface.co/fideus-labs/ome-zarr-rfc4-data"
DEST = "hf-data"


def main() -> int:
    if os.path.isdir(os.path.join(DEST, ".git")):
        print(f"updating {DEST} …")
        cmd = ["git", "-C", DEST, "pull", "--ff-only"]
    else:
        print(f"cloning {HF_URL} -> {DEST} …")
        cmd = ["git", "clone", HF_URL, DEST]
    try:
        subprocess.run(cmd, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"error: {exc}\n"
              f"Manual fallback: git clone {HF_URL} {DEST}", file=sys.stderr)
        return 1
    print(f"\nData ready. Run:\n"
          f"  python validate_rfc4.py --data-dir {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
