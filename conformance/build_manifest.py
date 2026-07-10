#!/usr/bin/env python3
"""Build the RFC-4 conformance manifest (conformance/manifest.yaml).

The manifest is the formal, tool-agnostic description of the suite. Every case
declares:
  - which normative RFC-4 requirement(s) it exercises (traceability),
  - a one-line rationale (why the case exists),
  - the expected canonical output (ground truth, authored by hand -- NOT produced
    by the reference tool, so the check is not circular).

Running this script also prints a coverage matrix (requirement -> cases) so the
suite can be shown to be complete (every requirement covered) and non-redundant
(every case maps to a distinct requirement / format / geometry).
"""
from __future__ import annotations

import json
import os
import sys

import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import validate_rfc4 as V  # noqa: E402  (for the vocabulary, kept in sync with the validator)

# --------------------------------------------------------------------------- #
# Normative RFC-4 requirements the suite must exercise
# --------------------------------------------------------------------------- #
REQUIREMENTS = {
    "R1": {"level": "MUST", "text": "orientation only on axes with type 'space' (never time/channel)"},
    "R2": {"level": "MUST", "text": "orientation is an object with both 'type' and 'value'"},
    "R3": {"level": "MUST", "text": "orientation.type is 'anatomical'"},
    "R4": {"level": "MUST", "text": "orientation.value is one of the 24 controlled-vocabulary terms"},
    "R5": {"level": "MUST", "text": "at most one direction per anatomical axis (no antonym-pair collision)"},
    "R6": {"level": "SHOULD", "text": "writers omit the field rather than serialize null (null == absent)"},
    "R7": {"level": "DEF", "text": "value names the lowest->highest coordinate direction (flip semantics)"},
    "R8": {"level": "SHOULD", "text": "subject roughly aligned to imaging axes (oblique -> warn)"},
    "R9": {"level": "COVER", "text": "full vocabulary incl. subject-local (PR#528) and quadruped terms"},
    "R10": {"level": "DERIVE", "text": "correct RFC-4 derivation from DICOM IOP / NIfTI affine / NRRD space directions"},
}

# Data lives at the root of the HF data repo (ome-zarr-rfc4-data); inputs are
# relative to that root. Conformance fixtures live in this code repo.
D = "."
C = "conformance/cases"

# --------------------------------------------------------------------------- #
# Cases. `expected` is the authored ground-truth canonical output.
# --------------------------------------------------------------------------- #
CASES = [
    # ---- OME-Zarr, valid (schema layer) ----
    dict(id="TC-16", title="Synthetic LPS baseline", format="ome-zarr",
         input=f"{D}/synthetic/ome-zarr/TC-16_synthetic_LPS.ome.zarr",
         requirements=["R2", "R3", "R4", "R7"], expect="valid",
         rationale="Baseline: three standard terms written explicitly; establishes the LPS reference.",
         expected=dict(rfc4_valid=True, axes={"z": "inferior-to-superior", "y": "anterior-to-posterior",
                                              "x": "right-to-left"}, violations=[])),
    dict(id="TC-17", title="Synthetic RAS baseline", format="ome-zarr",
         input=f"{D}/synthetic/ome-zarr/TC-17_synthetic_RAS.ome.zarr",
         requirements=["R7"], expect="valid",
         rationale="Flip pair of TC-16: x and y invert; proves the lowest->highest coordinate convention.",
         expected=dict(rfc4_valid=True, axes={"z": "inferior-to-superior", "y": "posterior-to-anterior",
                                              "x": "left-to-right"}, violations=[])),
    dict(id="TC-18", title="Skin superficial-to-deep", format="ome-zarr",
         input=f"{D}/synthetic/ome-zarr/TC-18_skin_superficial_deep.ome.zarr",
         requirements=["R9"], expect="valid",
         rationale="PR#528 subject-local layered-tissue term (distinct from TC-19/TC-20).",
         expected=dict(rfc4_valid=True, axes={"z": "superficial-to-deep"}, violations=[])),
    dict(id="TC-19", title="Epithelial apical-to-basal", format="ome-zarr",
         input=f"{D}/synthetic/ome-zarr/TC-19_epithelial_apical_basal.ome.zarr",
         requirements=["R9"], expect="valid",
         rationale="PR#528 epithelial polarity term (distinct term).",
         expected=dict(rfc4_valid=True, axes={"z": "apical-to-basal"}, violations=[])),
    dict(id="TC-20", title="Cardiac apex-to-base", format="ome-zarr",
         input=f"{D}/synthetic/ome-zarr/TC-20_cardiac_apex_base.ome.zarr",
         requirements=["R9"], expect="valid",
         rationale="PR#528 cardiac term (distinct term).",
         expected=dict(rfc4_valid=True, axes={"z": "apex-to-base"}, violations=[])),
    # ---- OME-Zarr, invalid (negatives, one violation each) ----
    dict(id="TC-C", title="Invalid vocabulary 'LPS'", format="ome-zarr",
         input=f"{D}/ome-zarr/TC-C_invalid_vocabulary.zip",
         requirements=["R4"], expect="invalid",
         rationale="'LPS' shorthand is not a vocabulary term; MUST be rejected.",
         expected=dict(rfc4_valid=False, violations=["bad-value"])),
    dict(id="TC-D", title="Orientation on time axis", format="ome-zarr",
         input=f"{D}/ome-zarr/TC-D_orientation_on_time_axis.zip",
         requirements=["R1"], expect="invalid",
         rationale="orientation on a type:time axis is forbidden; MUST be rejected.",
         expected=dict(rfc4_valid=False, violations=["orientation-on-non-space"])),
    dict(id="SC-03", title="Orientation on channel axis", format="ome-zarr",
         input=f"{C}/SC-03_channel_orientation.ome.zarr",
         requirements=["R1"], expect="invalid",
         rationale="type:channel variant of the non-space rule; isolates the single violation.",
         expected=dict(rfc4_valid=False, violations=["orientation-on-non-space"])),
    dict(id="SC-05", title="Missing orientation value", format="ome-zarr",
         input=f"{C}/SC-05_missing_value.ome.zarr",
         requirements=["R2"], expect="invalid",
         rationale="orientation without 'value' violates the required-fields rule.",
         expected=dict(rfc4_valid=False, violations=["missing-value"])),
    dict(id="SC-06", title="Bad orientation type", format="ome-zarr",
         input=f"{C}/SC-06_bad_type.ome.zarr",
         requirements=["R3"], expect="invalid",
         rationale="orientation.type 'geographical' is not 'anatomical'.",
         expected=dict(rfc4_valid=False, violations=["bad-type"])),
    dict(id="SC-07", title="Duplicate anatomical axis", format="ome-zarr",
         input=f"{C}/SC-07_duplicate_pair.ome.zarr",
         requirements=["R5"], expect="invalid",
         rationale="two axes on the left-to-right/right-to-left axis; only one allowed.",
         expected=dict(rfc4_valid=False, violations=["duplicate-anatomical-axis"])),
    # ---- OME-Zarr, valid-with-warning ----
    dict(id="SC-01", title="Quadruped vocabulary", format="ome-zarr",
         input=f"{C}/SC-01_quadruped_valid.ome.zarr",
         requirements=["R9"], expect="valid",
         rationale="quadruped terms (dorsal-to-ventral, rostral-to-caudal) MUST be accepted.",
         expected=dict(rfc4_valid=True, axes={"z": "dorsal-to-ventral", "y": "rostral-to-caudal",
                                              "x": "left-to-right"}, violations=[])),
    dict(id="SC-02", title="Null orientation", format="ome-zarr",
         input=f"{C}/SC-02_null_orientation.ome.zarr",
         requirements=["R6"], expect="valid",
         rationale="orientation:null == absent; valid, but a SHOULD-omit warning is emitted.",
         expected=dict(rfc4_valid=True, warnings=["null-orientation"], violations=[])),
    # ---- Cross-format derivation ----
    dict(id="TC-05", title="DICOM HFDR", format="dicom",
         input=f"{D}/dicom/TC-05_HFDR.dcm",
         requirements=["R10"], expect="valid",
         rationale="derive orientation from IOP=[0,-1,0,1,0,0]; PatientPosition ignored.",
         expected=dict(axes={"x": "posterior-to-anterior", "y": "right-to-left",
                             "z": "inferior-to-superior"})),
    dict(id="TC-06", title="DICOM HFDL", format="dicom",
         input=f"{D}/dicom/TC-06_HFDL.dcm",
         requirements=["R10", "R7"], expect="valid",
         rationale="mirror of TC-05 (L/R flip in the IOP derivation).",
         expected=dict(axes={"x": "anterior-to-posterior", "y": "left-to-right",
                             "z": "inferior-to-superior"})),
    dict(id="TC-11", title="NIfTI qform!=sform", format="nifti",
         input=f"{D}/nifti/TC-11_qform_sform_mismatch.nii.gz",
         requirements=["R10"], expect="valid",
         rationale="qform/sform ambiguity; a tool must document which transform it uses.",
         expected=dict(axes={"i": "right-to-left", "j": "posterior-to-anterior", "k": "inferior-to-superior"})),
    dict(id="TC-08", title="MNI avg152 LR (LAS)", format="nifti",
         input=f"{D}/nifti/avg152T1_LR_nifti.nii.gz",
         requirements=["R10", "R7"], expect="valid",
         rationale="real reference; neurological LAS. Flip pair with TC-09.",
         expected=dict(axes={"i": "right-to-left", "j": "posterior-to-anterior", "k": "inferior-to-superior"})),
    dict(id="TC-09", title="MNI avg152 RL (RAS)", format="nifti",
         input=f"{D}/nifti/avg152T1_RL_nifti.nii.gz",
         requirements=["R10", "R7"], expect="valid",
         rationale="real reference; radiological RAS. Proves L/R flip detection vs TC-08.",
         expected=dict(axes={"i": "left-to-right", "j": "posterior-to-anterior", "k": "inferior-to-superior"})),
    dict(id="TC-23", title="Canon axial DTI (dcm_qa_canon_61)", format="nifti",
         input=f"{D}/nifti/TC-23_canon_DTI_axial.nii.gz",
         requirements=["R10"], expect="valid",
         rationale="real Canon 3T DTI, axial strict (0deg off-axis); clean LAS derivation (BSD-2).",
         expected=dict(axes={"i": "right-to-left", "j": "posterior-to-anterior", "k": "inferior-to-superior"})),
    dict(id="TC-13", title="NRRD MRHead (LPS rotated)", format="nrrd",
         input=f"{D}/nrrd/MRHead.nrrd",
         requirements=["R10", "R8"], expect="valid",
         rationale="real NRRD, LPS with non-identity space directions; stresses dominant-axis derivation.",
         expected=dict(axes={"0": "anterior-to-posterior", "1": "superior-to-inferior", "2": "left-to-right"})),
    # ---- Real OME-Zarr with RFC-4 written (converted via ngff-zarr) ----
    dict(id="TC-21", title="Real Allen mouse (quadruped)", format="ome-zarr",
         input=f"{D}/real/ome-zarr/mouse_allen_quadruped.ome.zarr",
         requirements=["R9"], expect="valid",
         rationale="real mouse brain; quadruped terms written into OME-Zarr (from atlas 'asr').",
         expected=dict(rfc4_valid=True, axes={"z": "rostral-to-caudal", "y": "dorsal-to-ventral",
                                              "x": "right-to-left"}, violations=[])),
    dict(id="TC-22", title="Real foot CT (limb)", format="ome-zarr",
         input=f"{D}/real/ome-zarr/foot_cmb_limb.ome.zarr",
         requirements=["R9"], expect="valid",
         rationale="real foot; limb terms written into OME-Zarr; proximal-distal verified by bone mass.",
         expected=dict(rfc4_valid=True, axes={"z": "distal-to-proximal", "y": "dorsal-to-plantar"},
                       violations=[])),
    dict(id="TC-24", title="Real skin superficial-to-deep (Janelia)", format="ome-zarr",
         input=f"{D}/real/ome-zarr/skin_janelia_superficial_deep.ome.zarr",
         requirements=["R9"], expect="valid",
         rationale="real mouse skin FIB-SEM (jrc_mus-skin-1, CC BY 4.0); subject-local depth term on real data.",
         expected=dict(rfc4_valid=True, axes={"z": "superficial-to-deep"}, violations=[])),
    dict(id="TC-25", title="Real heart apex-to-base (Janelia)", format="ome-zarr",
         input=f"{D}/real/ome-zarr/heart_janelia_apex_base.ome.zarr",
         requirements=["R9"], expect="valid",
         rationale="real mouse heart FIB-SEM (jrc_mus-heart-1, CC BY 4.0); subject-local cardiac term on real data.",
         expected=dict(rfc4_valid=True, axes={"z": "apex-to-base"}, violations=[])),
    # ---- NIfTI oblique (precondition) ----
    dict(id="SC-04", title="Oblique NIfTI (30deg)", format="nifti",
         input=f"{C}/SC-04_oblique_nifti.nii.gz",
         requirements=["R8"], expect="valid",
         rationale="axes 30deg off; a conformant tool SHOULD warn (roughly-aligned precondition).",
         expected=dict(warnings=["not-roughly-aligned"])),
    dict(id="TC-10", title="Canon oblique DTI (dcm_qa_canon_61)", format="nifti",
         input=f"{D}/nifti/TC-10_canon_DTI_oblique_20d.nii.gz",
         requirements=["R8", "R10"], expect="valid",
         rationale="real oblique DTI, ~20deg on all views (36deg off-axis); real-data counterpart to SC-04.",
         expected=dict(axes={"i": "right-to-left", "j": "posterior-to-anterior", "k": "inferior-to-superior"},
                       warnings=["not-roughly-aligned"])),
]


def build() -> dict:
    return {
        "rfc4": {"version": "0.2.0", "spec": "https://ngff.openmicroscopy.org/rfc/4",
                 "pr": "https://github.com/ome/ngff/pull/528"},
        "canonical_output_contract": {
            "description": "A conformant tool, given one input, emits this JSON.",
            "fields": {
                "input": "path to the dataset",
                "format": "ome-zarr | nifti | dicom | nrrd",
                "rfc4_valid": "bool (ome-zarr schema cases only; null for derived formats)",
                "axes": "list of {name, type, orientation-value|null}",
                "violations": "list of {code, axis, message} (empty when valid)",
                "warnings": "list of {code, message}",
            },
        },
        "requirements": REQUIREMENTS,
        "cases": CASES,
    }


def coverage() -> None:
    by_req: dict[str, list[str]] = {r: [] for r in REQUIREMENTS}
    for case in CASES:
        for r in case["requirements"]:
            by_req[r].append(case["id"])
    print("Requirement coverage (requirement -> cases):")
    gaps = []
    for r, meta in REQUIREMENTS.items():
        cases = by_req[r]
        if not cases:
            gaps.append(r)
        print(f"  {r} [{meta['level']:6}] {len(cases):>2} case(s): {', '.join(cases) or '<<none>>'}")
    orphans = [c["id"] for c in CASES if not c["requirements"]]
    print(f"\n{len(CASES)} cases, {len(REQUIREMENTS)} requirements. "
          f"gaps: {gaps or 'none'}. cases with no requirement: {orphans or 'none'}")


def write_schema() -> str:
    """Emit a JSON Schema for a single RFC-4 orientation object (vocabulary in
    sync with the validator)."""
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://ngff.openmicroscopy.org/rfc/4/orientation.schema.json",
        "title": "OME-NGFF RFC-4 anatomical orientation",
        "description": "The value of an axis 'orientation' field (RFC-4). Only valid on type:space axes.",
        "type": "object",
        "required": ["type", "value"],
        "additionalProperties": False,
        "properties": {
            "type": {"const": "anatomical"},
            "value": {"enum": sorted(V.ANATOMICAL_VOCABULARY)},
        },
    }
    out = os.path.join(REPO, "conformance", "orientation.schema.json")
    with open(out, "w") as fh:
        json.dump(schema, fh, indent=2)
        fh.write("\n")
    return out


def main() -> None:
    manifest = build()
    out = os.path.join(REPO, "conformance", "manifest.yaml")
    with open(out, "w") as fh:
        yaml.safe_dump(manifest, fh, sort_keys=False, default_flow_style=False, width=100)
    schema_out = write_schema()
    print(f"wrote {out}  ({len(CASES)} cases)")
    print(f"wrote {schema_out}  ({len(V.ANATOMICAL_VOCABULARY)} vocabulary terms)\n")
    coverage()


if __name__ == "__main__":
    main()
