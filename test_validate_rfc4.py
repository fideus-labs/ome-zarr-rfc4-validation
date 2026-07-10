#!/usr/bin/env python3
"""Proof suite for the RFC-4 validator.

Three kinds of evidence, no pytest needed (plain asserts, exit 0 = all proven):

  A. POSITIVE   — every shipped test case meets its declared expectation.
  B. ADVERSARIAL— hand-crafted broken metadata must be REJECTED with the right
                  error code. This proves the checker actually fires and is not
                  a rubber stamp that passes everything.
  C. CROSS-CHECK— parsed OME-Zarr orientations equal the independent ground
                  truth in manifest.csv.

Run:  python test_validate_rfc4.py --data-dir RFC-4-Sample-Data
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

import validate_rfc4 as V

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
if not sys.stdout.isatty():
    PASS, FAIL = "PASS", "FAIL"

_n_pass = 0
_n_fail = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _n_pass, _n_fail
    mark = PASS if cond else FAIL
    if cond:
        _n_pass += 1
    else:
        _n_fail += 1
    print(f"  [{mark}] {label}" + (f"  — {detail}" if detail and not cond else ""))


def _axes_result(axes: list[dict]) -> V.DatasetResult:
    r = V.DatasetResult(name="synthetic", path="<memory>", kind="ome-zarr")
    V.validate_axes(axes, r)
    return r


def _codes(r: V.DatasetResult) -> set[str]:
    return {i.code for i in r.issues}


# --------------------------------------------------------------------------- #
# A. POSITIVE — shipped cases meet expectations
# --------------------------------------------------------------------------- #

def positive(data_dir: str) -> None:
    print("A. POSITIVE — shipped cases meet their declared expectation")
    results = V.run(data_dir)
    for r in results:
        if r.expectation_met is None:
            print(f"  [ skip ] {r.name} (file absent)")
            continue
        check(f"{r.name} (expect {'valid' if r.expect_valid else 'INVALID'})",
              r.expectation_met is True,
              detail=f"met={r.expectation_met}")


# --------------------------------------------------------------------------- #
# B. ADVERSARIAL — broken metadata must be rejected with the right code
# --------------------------------------------------------------------------- #

def adversarial() -> None:
    print("\nB. ADVERSARIAL — injected violations must be caught")

    # A fully valid axis set must produce NO errors.
    ok = _axes_result([
        {"name": "z", "type": "space", "orientation": {"type": "anatomical", "value": "inferior-to-superior"}},
        {"name": "y", "type": "space", "orientation": {"type": "anatomical", "value": "anterior-to-posterior"}},
        {"name": "x", "type": "space", "orientation": {"type": "anatomical", "value": "right-to-left"}},
    ])
    check("valid LPS axes -> no errors", not ok.errors, detail=str(_codes(ok)))

    cases = [
        ("orientation on a time axis",
         [{"name": "t", "type": "time", "orientation": {"type": "anatomical", "value": "inferior-to-superior"}}],
         "orientation-on-non-space"),
        ("value 'LPS' not in vocabulary",
         [{"name": "x", "type": "space", "orientation": {"type": "anatomical", "value": "LPS"}}],
         "bad-value"),
        ("missing orientation.type",
         [{"name": "x", "type": "space", "orientation": {"value": "right-to-left"}}],
         "missing-type"),
        ("missing orientation.value",
         [{"name": "x", "type": "space", "orientation": {"type": "anatomical"}}],
         "missing-value"),
        ("type not 'anatomical'",
         [{"name": "x", "type": "space", "orientation": {"type": "geographical", "value": "right-to-left"}}],
         "bad-type"),
        ("two axes on the same L/R anatomical axis",
         [{"name": "x", "type": "space", "orientation": {"type": "anatomical", "value": "left-to-right"}},
          {"name": "y", "type": "space", "orientation": {"type": "anatomical", "value": "right-to-left"}}],
         "duplicate-anatomical-axis"),
        ("orientation on a channel axis",
         [{"name": "c", "type": "channel", "orientation": {"type": "anatomical", "value": "left-to-right"}}],
         "orientation-on-non-space"),
    ]
    for label, axes, expected_code in cases:
        r = _axes_result(axes)
        got = _codes(r)
        check(f"reject: {label} -> [{expected_code}]",
              expected_code in got and bool(r.errors),
              detail=f"got {got}")

    # null orientation must raise the WARN (writers SHOULD omit).
    rn = _axes_result([{"name": "x", "type": "space", "orientation": None}])
    check("null orientation -> null-orientation warning",
          "null-orientation" in _codes(rn), detail=str(_codes(rn)))

    # Every one of the 24 vocabulary terms must be accepted as a value.
    all_ok = True
    for term in sorted(V.ANATOMICAL_VOCABULARY):
        r = _axes_result([{"name": "x", "type": "space",
                           "orientation": {"type": "anatomical", "value": term}}])
        if any(i.code == "bad-value" for i in r.issues):
            all_ok = False
    check(f"all {len(V.ANATOMICAL_VOCABULARY)} vocabulary terms accepted", all_ok)
    check("vocabulary has exactly 24 terms", len(V.ANATOMICAL_VOCABULARY) == 24,
          detail=str(len(V.ANATOMICAL_VOCABULARY)))


# --------------------------------------------------------------------------- #
# C. CROSS-CHECK — parsed orientations vs manifest.csv ground truth
# --------------------------------------------------------------------------- #

def parsed_orientations(path: str) -> dict[str, str]:
    ome = V.load_ome_metadata(path)
    found: dict[str, str] = {}
    if ome:
        for ms in ome.get("multiscales", []):
            for ax in ms.get("axes", []):
                o = ax.get("orientation")
                if isinstance(o, dict) and "value" in o:
                    found[ax["name"]] = o["value"]
    return found


def _manifest_orientations(cell: str) -> dict[str, str]:
    """Parse a manifest 'orientation' cell ('z:term; y:term; x:term') -> {axis: term}."""
    out: dict[str, str] = {}
    for tok in cell.split(";"):
        tok = tok.strip()
        if ":" in tok:
            name, val = tok.split(":", 1)
            out[name.strip()] = val.strip()
    return out


def cross_check(data_dir: str) -> None:
    print("\nC. CROSS-CHECK — parsed orientations == manifest.csv ground truth")
    manifest = os.path.join(data_dir, "manifest.csv")
    if not os.path.exists(manifest):
        print(f"  [ skip ] {manifest} absent (run fetch_data.py)")
        return
    with open(manifest, newline="") as fh:
        rows = list(csv.DictReader(fh))
    # cross-check every valid OME-Zarr case: parsed file orientation == manifest
    for row in rows:
        if row.get("format") != "ome-zarr" or row.get("expect") != "valid":
            continue
        path = os.path.join(data_dir, row["path"])
        if not os.path.exists(path):
            print(f"  [ skip ] {row['test_id']} ({row['path']} absent)")
            continue
        got = parsed_orientations(path)
        for axis, want in _manifest_orientations(row.get("orientation", "")).items():
            if want.startswith("("):  # e.g. "(unannotated)"
                continue
            check(f"{row['test_id']} axis {axis} == {want!r}", got.get(axis) == want,
                  detail=f"parsed {got.get(axis)!r}")


def _run_case(case: dict, repo_root: str, data_dir: str):
    """Run the reference validator on one manifest case; return the DatasetResult.

    Manifest inputs are relative to the data root (e.g. ``./synthetic/…``) except
    conformance fixtures (``conformance/cases/…``) which ship with the code, so
    try the data dir first, then the repo."""
    path = next((os.path.join(base, case["input"]) for base in (data_dir, repo_root)
                 if os.path.exists(os.path.join(base, case["input"]))), None)
    if path is None:
        return None
    fmt = case["format"]
    if fmt == "ome-zarr":
        return V.validate_ome_zarr(path, case["id"])
    if fmt == "nifti":
        return V.analyze_nifti(path, case["id"])
    if fmt == "dicom":
        return V.analyze_dicom(path, case["id"])
    if fmt == "nrrd":
        return V.analyze_nrrd(path, case["id"])
    return None


def manifest_parity(repo_root: str, data_dir: str) -> None:
    """D. Every validator output must match the manifest's authored `expected`.

    This locks the tool-agnostic manifest to the reference implementation: if a
    derivation or a violation code drifts, the manifest and the tool disagree
    and this fails. (Subsumes a separate NRRD ground-truth check.)"""
    print("\nD. MANIFEST PARITY — validator output == conformance/manifest.yaml `expected`")
    try:
        import yaml
    except ImportError:
        print("  [ skip ] pyyaml not installed")
        return
    manifest = yaml.safe_load(open(os.path.join(repo_root, "conformance", "manifest.yaml")))
    for case in manifest["cases"]:
        r = _run_case(case, repo_root, data_dir)
        if r is None:
            print(f"  [ skip ] {case['id']} (input absent)")
            continue
        exp = case.get("expected", {})
        codes = {i.code for i in r.issues}
        if case["format"] == "ome-zarr":
            if "rfc4_valid" in exp:
                check(f"{case['id']} rfc4_valid == {exp['rfc4_valid']}",
                      r.is_rfc4_valid == exp["rfc4_valid"], detail=f"got {r.is_rfc4_valid}")
            for code in exp.get("violations", []):
                check(f"{case['id']} raises [{code}]", code in codes, detail=str(codes))
            got = {s.split(" (")[0].split(":", 1)[0].strip():
                   s.split(":", 1)[1].strip() for s in r.axes_summary if ":" in s}
            for axis, want in exp.get("axes", {}).items():
                check(f"{case['id']} axis {axis} == {want!r}", got.get(axis) == want,
                      detail=f"got {got.get(axis)!r}")
        else:  # derived formats: compare on the axes_summary text + warning codes
            summary = " | ".join(r.axes_summary)
            for axis, want in exp.get("axes", {}).items():
                check(f"{case['id']} axis {axis} -> {want!r}",
                      f"{axis}: {want}" in summary or want in summary, detail=summary)
        for code in exp.get("warnings", []):
            check(f"{case['id']} warns [{code}]", code in codes, detail=str(codes))


def vocab_coverage(data_dir: str) -> None:
    """E. The sample corpus must exercise every one of the 24 vocabulary terms."""
    print("\nE. VOCABULARY COVERAGE — every RFC-4 term appears in the data")
    import glob
    used = set()
    for p in glob.glob(os.path.join(data_dir, "**", "*.ome.zarr"), recursive=True):
        ome = V.load_ome_metadata(p)
        if not ome:
            continue
        for ms in ome.get("multiscales", []):
            for ax in ms.get("axes", []):
                o = ax.get("orientation")
                if isinstance(o, dict) and o.get("value"):
                    used.add(o["value"])
    missing = sorted(set(V.ANATOMICAL_VOCABULARY) - used)
    if not glob.glob(os.path.join(data_dir, "**", "*.ome.zarr"), recursive=True):
        print("  [ skip ] no OME-Zarr under data dir (run fetch_data.py)")
        return
    check(f"all 24 terms present ({len(used)}/24)", not missing, detail=f"missing {missing}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="RFC-4-Sample-Data")
    args = ap.parse_args()
    repo_root = os.path.dirname(os.path.abspath(__file__))
    positive(args.data_dir)
    adversarial()
    cross_check(args.data_dir)
    manifest_parity(repo_root, args.data_dir)
    vocab_coverage(args.data_dir)
    print(f"\n{'=' * 60}\n{_n_pass} checks passed, {_n_fail} failed")
    return 0 if _n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
