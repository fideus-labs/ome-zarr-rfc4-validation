#!/usr/bin/env python3
"""RFC-4 conformance driver.

Runs any tool's CLI against every case in ``conformance/manifest.yaml`` and diffs
the tool's *canonical output* (see the manifest's ``canonical_output_contract``)
against the authored ground truth. This is what lets an *arbitrary* implementation
prove RFC-4 conformance -- not just this repo's reference validator.

A conformant tool is a CLI that, given one input path, prints this JSON to stdout::

    {"input": ..., "format": "ome-zarr|nifti|dicom|nrrd",
     "rfc4_valid": bool|null, "axes": {name: value|null},
     "violations": [code, ...], "warnings": [code, ...]}

Usage
-----
Default (drive this repo's reference validator -- a self-conformance check)::

    python conformance/run_conformance.py --data-dir ../ome-zarr-rfc4-data

Drive another tool (the ``{input}`` placeholder is replaced with each case path)::

    python conformance/run_conformance.py --data-dir ../ome-zarr-rfc4-data \
        --tool "ngff-zarr conformance {input}"

Exit code is 0 iff every case conforms.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MANIFEST = os.path.join(HERE, "manifest.yaml")

# Default tool: this repo's reference validator emitting the canonical contract.
DEFAULT_TOOL = f'{shlex.quote(sys.executable)} {shlex.quote(os.path.join(REPO, "validate_rfc4.py"))} --emit-canonical {{input}}'


def resolve_input(rel: str, data_dir: str) -> str | None:
    """Locate a case input: sample data lives in the data repo; conformance
    fixtures ship in this code repo. Try both roots."""
    rel = rel[2:] if rel.startswith("./") else rel
    for base in (data_dir, REPO, "."):
        cand = os.path.join(base, rel)
        if os.path.exists(cand):
            return cand
    return None


def run_tool(tool: str, input_path: str) -> tuple[dict | None, str]:
    """Run the tool CLI on one input; return (parsed_json, error_message)."""
    cmd = [tok.replace("{input}", input_path) for tok in shlex.split(tool)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"tool failed to run: {exc}"
    if proc.returncode != 0:
        return None, f"tool exited {proc.returncode}: {proc.stderr.strip()[:200]}"
    try:
        return json.loads(proc.stdout), ""
    except json.JSONDecodeError:
        return None, f"tool output was not valid JSON: {proc.stdout.strip()[:200]}"


def compare(expected: dict, got: dict) -> list[str]:
    """Return a list of mismatch descriptions (empty == conforms)."""
    problems: list[str] = []

    if expected.get("rfc4_valid") is not None:
        if got.get("rfc4_valid") != expected["rfc4_valid"]:
            problems.append(f"rfc4_valid: expected {expected['rfc4_valid']}, got {got.get('rfc4_valid')}")

    got_axes = got.get("axes") or {}
    for axis, want in (expected.get("axes") or {}).items():
        if got_axes.get(axis) != want:
            problems.append(f"axis {axis!r}: expected {want!r}, got {got_axes.get(axis)!r}")

    # Codes are checked as a subset: the tool MUST report at least the expected
    # violations/warnings (it may report the same code once per offending axis).
    for key in ("violations", "warnings"):
        want = set(expected.get(key) or [])
        have = {v["code"] if isinstance(v, dict) else v for v in (got.get(key) or [])}
        missing = want - have
        if missing:
            problems.append(f"{key}: missing {sorted(missing)} (got {sorted(have)})")

    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Drive a tool against the RFC-4 conformance manifest.")
    ap.add_argument("--data-dir", default="hf-data",
                    help="path to the sample data (default: %(default)s, as written by fetch_data.py)")
    ap.add_argument("--tool", default=DEFAULT_TOOL,
                    help="CLI template emitting the canonical JSON; '{input}' is the dataset path")
    ap.add_argument("--format", action="append", metavar="FMT", dest="formats",
                    help="only run cases of this format (repeatable). Use it to scope the "
                         "suite to what a tool actually reads, e.g. --format ome-zarr for "
                         "an OME-Zarr-only implementation such as ngff-zarr")
    ap.add_argument("--manifest", default=MANIFEST)
    ap.add_argument("--json", metavar="FILE", help="also write a JSON report")
    args = ap.parse_args(argv)

    manifest = yaml.safe_load(open(args.manifest))
    cases = manifest["cases"]
    total_cases = len(cases)
    if args.formats:
        wanted = set(args.formats)
        cases = [case for case in cases if case.get("format") in wanted]
    print(f"conformance driver — {len(cases)} cases", end="")
    if args.formats:
        print(f" (of {total_cases}; format: {', '.join(sorted(set(args.formats)))})", end="")
    print()
    print(f"tool: {args.tool}\n" + "=" * 72)

    results, passed, failed, skipped = [], 0, 0, 0
    for case in cases:
        cid, title = case["id"], case.get("title", "")
        path = resolve_input(case["input"], args.data_dir)
        if path is None:
            print(f"[SKIP] {cid} {title} — input not found ({case['input']})")
            skipped += 1
            results.append({"id": cid, "status": "skip", "reason": "input not found"})
            continue

        got, err = run_tool(args.tool, path)
        if got is None:
            print(f"[FAIL] {cid} {title} — {err}")
            failed += 1
            results.append({"id": cid, "status": "fail", "reason": err})
            continue

        problems = compare(case.get("expected", {}), got)
        if problems:
            print(f"[FAIL] {cid} {title}")
            for p in problems:
                print(f"       · {p}")
            failed += 1
            results.append({"id": cid, "status": "fail", "problems": problems})
        else:
            print(f"[PASS] {cid} {title}")
            passed += 1
            results.append({"id": cid, "status": "pass"})

    print("=" * 72)
    print(f"Total {len(cases)}  ·  {passed} passed  ·  {failed} failed  ·  {skipped} skipped")
    if args.json:
        json.dump({"tool": args.tool, "results": results,
                   "summary": {"passed": passed, "failed": failed, "skipped": skipped}},
                  open(args.json, "w"), indent=2)
        print(f"JSON report → {args.json}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
