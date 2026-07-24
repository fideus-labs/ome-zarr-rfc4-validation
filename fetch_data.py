#!/usr/bin/env python3
"""Fetch the RFC-4 sample data.

The images live in the Hugging Face dataset repo (the source of truth) and are
mirrored to a public, credential-free Filebase S3 bucket. Either source is
fetched into ./hf-data so the validator and conformance suite can run against
real data:

    python fetch_data.py                 # from Hugging Face (git clone/pull, needs git-lfs)
    python fetch_data.py --source s3      # from the Filebase S3 mirror (needs s5cmd)

    python validate_rfc4.py --data-dir hf-data
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

HF_URL = "https://huggingface.co/fideus-labs/ome-zarr-rfc4-data"
S3_ENDPOINT = "https://s3.filebase.io"
S3_BUCKET = "s3://ome-zarr-rfc4"
S3_HTTP = "https://ome-zarr-rfc4.s3.filebase.io"
DEST = "hf-data"


def fetch_hf(dest: str) -> int:
    """Clone (or fast-forward) the Hugging Face dataset repo into ``dest``."""
    if os.path.isdir(os.path.join(dest, ".git")):
        print(f"updating {dest} from Hugging Face …")
        cmd = ["git", "-C", dest, "pull", "--ff-only"]
    else:
        print(f"cloning {HF_URL} -> {dest} …")
        cmd = ["git", "clone", HF_URL, dest]
    try:
        subprocess.run(cmd, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"error: {exc}\n"
              f"Manual fallback: git clone {HF_URL} {dest}", file=sys.stderr)
        return 1
    return 0


def fetch_s3(dest: str) -> int:
    """Download the data from the public Filebase S3 mirror into ``dest``.

    Uses s5cmd with anonymous (``--no-sign-request``) access; the bucket is
    public, so no credentials are needed.
    """
    if shutil.which("s5cmd") is None:
        print("error: s5cmd not found -- install it with\n"
              "  pixi global install s5cmd   (or see https://github.com/peak/s5cmd)\n"
              f"or download files directly over HTTP from {S3_HTTP}/",
              file=sys.stderr)
        return 1
    os.makedirs(dest, exist_ok=True)
    print(f"syncing {S3_BUCKET} -> {dest} (anonymous) …")
    cmd = ["s5cmd", "--no-sign-request", f"--endpoint-url={S3_ENDPOINT}",
           "sync", f"{S3_BUCKET}/*", f"{dest}/"]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch the RFC-4 sample data.")
    parser.add_argument(
        "--source", choices=["hf", "s3"], default="hf",
        help="hf = Hugging Face git repo (default, needs git-lfs); "
             "s3 = Filebase S3 mirror (needs s5cmd)")
    parser.add_argument(
        "--dest", default=DEST, help=f"destination directory (default: {DEST})")
    args = parser.parse_args()

    rc = fetch_hf(args.dest) if args.source == "hf" else fetch_s3(args.dest)
    if rc == 0:
        print(f"\nData ready. Run:\n"
              f"  python validate_rfc4.py --data-dir {args.dest}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
