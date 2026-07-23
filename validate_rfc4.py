#!/usr/bin/env python3
"""RFC-4 (OME-NGFF axis anatomical orientation) validator.

Validates the ``orientation`` metadata introduced by OME-NGFF RFC-4
(https://ngff.openmicroscopy.org/rfc/4, merged in ome/ngff#528) against the
normative rules of the spec, and cross-checks the synthetic test dataset in
``RFC-4-Sample-Data/`` against its known ground truth.

RFC-4 in one sentence: an optional ``orientation`` object
``{"type": "anatomical", "value": <term>}`` may be attached to *spatial* axes
(``type: "space"``) of an OME-NGFF multiscale, where ``<term>`` is one of 24
controlled-vocabulary directions describing the lowest->highest coordinate
direction of that axis.

The OME-Zarr part is dependency-free (stdlib ``json``/``zipfile`` only).
NIfTI and DICOM analysis is optional and activates only if ``nibabel`` /
``pydicom`` are importable.

Usage:
    python validate_rfc4.py [--data-dir RFC-4-Sample-Data] [--json report.json]

Exit code is 0 when every dataset matches its expectation, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile
from dataclasses import dataclass, field
from typing import Any, Iterable

# Directory of this script; conformance fixtures (conformance/cases/) resolve
# against it, independently of the --data-dir sample-data location.
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------- #
# RFC-4 controlled vocabulary
# --------------------------------------------------------------------------- #

# The 24 allowed anatomical-orientation values, grouped by antonym pair. Each
# inner tuple is a pair of opposite directions along the same anatomical axis.
ANATOMICAL_PAIRS: tuple[tuple[str, str], ...] = (
    ("left-to-right", "right-to-left"),
    ("anterior-to-posterior", "posterior-to-anterior"),
    ("inferior-to-superior", "superior-to-inferior"),
    ("dorsal-to-ventral", "ventral-to-dorsal"),
    ("dorsal-to-palmar", "palmar-to-dorsal"),
    ("dorsal-to-plantar", "plantar-to-dorsal"),
    ("rostral-to-caudal", "caudal-to-rostral"),
    ("cranial-to-caudal", "caudal-to-cranial"),
    ("proximal-to-distal", "distal-to-proximal"),
    ("superficial-to-deep", "deep-to-superficial"),
    ("apical-to-basal", "basal-to-apical"),
    ("apex-to-base", "base-to-apex"),
)

ANATOMICAL_VOCABULARY: frozenset[str] = frozenset(v for pair in ANATOMICAL_PAIRS for v in pair)

# value -> the anatomical axis (pair) it belongs to, used for the "one direction
# per anatomical axis" mutual-exclusion rule.
_VALUE_TO_PAIR: dict[str, tuple[str, str]] = {v: pair for pair in ANATOMICAL_PAIRS for v in pair}

VALID_ORIENTATION_TYPES: frozenset[str] = frozenset({"anatomical"})

# NIfTI / nibabel axis code -> RFC-4 value. An axis code names the anatomical
# direction the voxel index increases toward; the RFC-4 value names the same
# direction as lowest->highest, so e.g. index increasing toward R == left-to-right.
AXCODE_TO_RFC4: dict[str, str] = {
    "R": "left-to-right",
    "L": "right-to-left",
    "A": "posterior-to-anterior",
    "P": "anterior-to-posterior",
    "S": "inferior-to-superior",
    "I": "superior-to-inferior",
}

# LPS unit direction (patient coordinate) -> RFC-4 value, for DICOM IOP cosines.
# DICOM patient axes: +x = Left, +y = Posterior, +z = Superior.
_LPS_DIR_TO_RFC4: dict[tuple[int, int, int], str] = {
    (1, 0, 0): "right-to-left",       # +x points to patient Left
    (-1, 0, 0): "left-to-right",
    (0, 1, 0): "anterior-to-posterior",   # +y points Posterior
    (0, -1, 0): "posterior-to-anterior",
    (0, 0, 1): "inferior-to-superior",    # +z points Superior
    (0, 0, -1): "superior-to-inferior",
}

# NRRD `space` anatomical letter -> its unit vector in LPS world coordinates.
_ANAT_LETTER_TO_LPS: dict[str, tuple[int, int, int]] = {
    "L": (1, 0, 0), "R": (-1, 0, 0),
    "P": (0, 1, 0), "A": (0, -1, 0),
    "S": (0, 0, 1), "I": (0, 0, -1),
}

# Shared threshold: an axis more than this many degrees off the nearest anatomical
# axis trips the RFC-4 "roughly aligned to imaging axes" precondition warning.
OBLIQUE_DEG = 15.0


# --------------------------------------------------------------------------- #
# Result model
# --------------------------------------------------------------------------- #

SEV_ERROR = "ERROR"
SEV_WARN = "WARN"
SEV_INFO = "INFO"


@dataclass
class Issue:
    severity: str
    code: str
    message: str


@dataclass
class DatasetResult:
    name: str
    path: str
    kind: str  # "ome-zarr" | "nifti" | "dicom"
    issues: list[Issue] = field(default_factory=list)
    axes_summary: list[str] = field(default_factory=list)
    # Structured axis -> orientation value (for the canonical conformance output).
    axis_values: dict[str, str | None] = field(default_factory=dict)
    # Expectation bookkeeping (filled by the test runner layer).
    expect_valid: bool | None = None
    expectation_met: bool | None = None
    notes: list[str] = field(default_factory=list)

    def add(self, severity: str, code: str, message: str) -> None:
        self.issues.append(Issue(severity, code, message))

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == SEV_ERROR]

    @property
    def is_rfc4_valid(self) -> bool:
        return not self.errors


# --------------------------------------------------------------------------- #
# OME metadata loading (Zarr v2 .zattrs and Zarr v3 zarr.json, dir or .zip)
# --------------------------------------------------------------------------- #

def _extract_ome(meta: Any) -> dict | None:
    """Return the OME dict (containing ``multiscales``) from a parsed metadata blob."""
    if not isinstance(meta, dict):
        return None
    # Zarr v3 zarr.json: {"attributes": {"ome": {...}}}
    attrs = meta.get("attributes")
    if isinstance(attrs, dict):
        ome = attrs.get("ome")
        if isinstance(ome, dict) and "multiscales" in ome:
            return ome
        if "multiscales" in attrs:  # attributes hold multiscales directly
            return attrs
    # Zarr v2 .zattrs (or a bare attributes object)
    ome = meta.get("ome")
    if isinstance(ome, dict) and "multiscales" in ome:
        return ome
    if "multiscales" in meta:
        return meta
    return None


def load_ome_from_dir(path: str) -> dict | None:
    for meta_name in ("zarr.json", ".zattrs"):
        fpath = os.path.join(path, meta_name)
        if os.path.isfile(fpath):
            with open(fpath, encoding="utf-8") as fh:
                ome = _extract_ome(json.load(fh))
            if ome is not None:
                return ome
    return None


def load_ome_from_zip(path: str) -> dict | None:
    with zipfile.ZipFile(path) as zf:
        candidates = [
            n for n in zf.namelist()
            if n.endswith("zarr.json") or n.endswith(".zattrs")
        ]
        # Prefer the shallowest metadata file (the multiscale root).
        candidates.sort(key=lambda n: (n.count("/"), len(n)))
        for name in candidates:
            try:
                ome = _extract_ome(json.loads(zf.read(name)))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if ome is not None:
                return ome
    return None


def load_ome_metadata(path: str) -> dict | None:
    if path.endswith(".zip") and zipfile.is_zipfile(path):
        return load_ome_from_zip(path)
    if os.path.isdir(path):
        return load_ome_from_dir(path)
    return None


# --------------------------------------------------------------------------- #
# Core RFC-4 validation
# --------------------------------------------------------------------------- #

def validate_orientation_object(orient: Any, axis_name: str, result: DatasetResult) -> str | None:
    """Validate a single ``orientation`` object. Returns its value if usable."""
    if orient is None:
        # null and absent are equivalent; writers SHOULD omit rather than serialize null.
        result.add(SEV_WARN, "null-orientation",
                   f"axis '{axis_name}': orientation is null; writers SHOULD omit the field instead")
        return None
    if not isinstance(orient, dict):
        result.add(SEV_ERROR, "orientation-not-object",
                   f"axis '{axis_name}': orientation must be an object, got {type(orient).__name__}")
        return None

    otype = orient.get("type")
    ovalue = orient.get("value")
    if otype is None:
        result.add(SEV_ERROR, "missing-type",
                   f"axis '{axis_name}': orientation.type is required")
    elif otype not in VALID_ORIENTATION_TYPES:
        result.add(SEV_ERROR, "bad-type",
                   f"axis '{axis_name}': orientation.type must be 'anatomical', got {otype!r}")

    if ovalue is None:
        result.add(SEV_ERROR, "missing-value",
                   f"axis '{axis_name}': orientation.value is required")
        return None
    if ovalue not in ANATOMICAL_VOCABULARY:
        result.add(SEV_ERROR, "bad-value",
                   f"axis '{axis_name}': orientation.value {ovalue!r} is not one of the "
                   f"24 RFC-4 anatomical terms")
        return None
    return ovalue


def validate_axes(axes: list[dict], result: DatasetResult) -> None:
    seen_pairs: dict[tuple[str, str], str] = {}
    for ax in axes:
        name = ax.get("name", "?")
        atype = ax.get("type")
        has_orient = "orientation" in ax
        orient = ax.get("orientation")

        value = None
        if has_orient:
            # MUST: orientation only on spatial axes. null == absent, so a null
            # orientation is neither an error nor an "on-non-space" violation.
            if orient is not None and atype != "space":
                result.add(SEV_ERROR, "orientation-on-non-space",
                           f"axis '{name}' has type {atype!r} but carries an orientation; "
                           f"RFC-4 forbids orientation on non-space axes")
            value = validate_orientation_object(orient, name, result)

        # SHOULD: spatial axes are expected to carry an orientation.
        if atype == "space" and not has_orient:
            result.add(SEV_INFO, "space-without-orientation",
                       f"axis '{name}' is spatial but has no orientation (allowed; RFC-4 is optional)")

        if value is not None:
            pair = _VALUE_TO_PAIR[value]
            if pair in seen_pairs:
                result.add(SEV_ERROR, "duplicate-anatomical-axis",
                           f"axes '{seen_pairs[pair]}' and '{name}' both describe the "
                           f"{pair[0]}/{pair[1]} anatomical axis; only one is allowed per axis set")
            else:
                seen_pairs[pair] = name

        if value is not None:
            result.axis_values[name] = value
        label = f"{name} ({atype})"
        if has_orient:
            label += f": {value if value is not None else orient}"
        result.axes_summary.append(label)


def validate_ome_zarr(path: str, name: str) -> DatasetResult:
    result = DatasetResult(name=name, path=path, kind="ome-zarr")
    ome = load_ome_metadata(path)
    if ome is None:
        result.add(SEV_ERROR, "no-metadata", "could not locate OME multiscales metadata")
        return result

    version = ome.get("version")
    if version is not None:
        result.notes.append(f"OME-NGFF version {version}")

    multiscales = ome.get("multiscales")
    if not isinstance(multiscales, list) or not multiscales:
        result.add(SEV_ERROR, "no-multiscales", "metadata has no non-empty 'multiscales' array")
        return result

    for i, ms in enumerate(multiscales):
        axes = ms.get("axes")
        if not isinstance(axes, list):
            result.add(SEV_ERROR, "no-axes", f"multiscale[{i}] has no 'axes' array")
            continue
        validate_axes(axes, result)
    return result


# --------------------------------------------------------------------------- #
# Optional nibabel-backed analysis (NIfTI, MINC, Analyze)
# --------------------------------------------------------------------------- #

def _derive_orientation_from_affine(affine: Any, result: DatasetResult) -> None:
    """Derive i/j/k RFC-4 terms + an oblique warning from a nibabel-style affine.

    Shared by every nibabel-backed analyzer (NIfTI, MINC, Analyze). An axis code
    names the anatomical direction the voxel index increases toward (mapped to the
    RFC-4 term via AXCODE_TO_RFC4); an axis more than OBLIQUE_DEG off its nearest
    anatomical axis trips the 'roughly aligned' precondition warning.
    """
    import numpy as np
    import nibabel as nib

    axcodes = nib.orientations.aff2axcodes(affine)
    result.notes.append(f"affine axcodes={''.join(axcodes)}")
    for axis_label, code in zip(("i", "j", "k"), axcodes):
        val = AXCODE_TO_RFC4.get(code, "?")
        result.axis_values[axis_label] = val
        result.axes_summary.append(f"{axis_label} [{code}]: {val}")

    cosines = np.asarray(affine)[:3, :3]
    norms = np.linalg.norm(cosines, axis=0)
    for axis_label, i in zip(("i", "j", "k"), range(3)):
        if norms[i] == 0:
            continue
        dominant = float(np.max(np.abs(cosines[:, i])) / norms[i])
        deg = float(np.degrees(np.arccos(min(1.0, dominant))))
        if deg > OBLIQUE_DEG:
            result.add(SEV_WARN, "not-roughly-aligned",
                       f"axis {axis_label} is {deg:.0f}deg off the nearest anatomical axis; "
                       f"the RFC-4 'roughly aligned' precondition may not hold")


def analyze_nifti(path: str, name: str) -> DatasetResult:
    result = DatasetResult(name=name, path=path, kind="nifti")
    try:
        import nibabel as nib
    except ImportError:
        result.add(SEV_INFO, "nibabel-missing", "install nibabel to analyze NIfTI orientation")
        return result

    img = nib.load(path)
    hdr = img.header
    qform_code = int(hdr["qform_code"])
    sform_code = int(hdr["sform_code"])
    result.notes.append(f"qform_code={qform_code}, sform_code={sform_code}")

    _derive_orientation_from_affine(img.affine, result)

    # Report qform/sform disagreement (the TC-11 ambiguity case).
    if qform_code > 0 and sform_code > 0:
        q_ax = nib.orientations.aff2axcodes(img.get_qform())
        s_ax = nib.orientations.aff2axcodes(img.get_sform())
        if q_ax != s_ax:
            result.add(SEV_WARN, "qform-sform-axcode-mismatch",
                       f"qform axcodes {''.join(q_ax)} != sform axcodes {''.join(s_ax)}")
        import numpy as np
        if not np.allclose(img.get_qform(), img.get_sform(), atol=1e-4):
            result.add(SEV_WARN, "qform-sform-matrix-mismatch",
                       "qform and sform matrices differ; a converter MUST document which it uses "
                       "(NIfTI spec: sform takes precedence when sform_code > 0)")
    return result


def analyze_minc(path: str, name: str) -> DatasetResult:
    """MINC (.mnc): nibabel reads MINC1/MINC2 like any spatial image; derive i/j/k."""
    result = DatasetResult(name=name, path=path, kind="minc")
    try:
        import nibabel as nib
    except ImportError:
        result.add(SEV_INFO, "nibabel-missing", "install nibabel to analyze MINC orientation")
        return result
    _derive_orientation_from_affine(nib.load(path).affine, result)
    return result


def analyze_analyze(path: str, name: str) -> DatasetResult:
    """Analyze 7.5 (.hdr/.img): no formal orientation field; nibabel derives an
    affine from the pixdim signs (SPM/FSL convention). We report what it derives —
    the orientation is genuinely ambiguous, which is the point of the TC-30 case."""
    result = DatasetResult(name=name, path=path, kind="analyze")
    try:
        import nibabel as nib
    except ImportError:
        result.add(SEV_INFO, "nibabel-missing", "install nibabel to analyze Analyze orientation")
        return result
    result.notes.append("Analyze 7.5 has no formal orientation; derived from pixdim signs (ambiguous)")
    _derive_orientation_from_affine(nib.load(path).affine, result)
    return result


# --------------------------------------------------------------------------- #
# Optional DICOM analysis (pydicom)
# --------------------------------------------------------------------------- #

def _lps_to_rfc4(vec: Iterable[float]) -> tuple[str | None, float]:
    """Map an LPS direction vector to (RFC-4 value, degrees off the nearest axis).

    Uses the dominant axis (not integer rounding), so it degrades gracefully on
    oblique vectors instead of snapping 0.7 -> 1.
    """
    import numpy as np
    v = np.asarray(list(vec), dtype=float)
    norm = float(np.linalg.norm(v))
    if norm == 0:
        return None, 0.0
    u = v / norm
    dom = int(np.argmax(np.abs(u)))
    sign = 1 if u[dom] >= 0 else -1
    key = tuple(sign if k == dom else 0 for k in range(3))
    deg = float(np.degrees(np.arccos(min(1.0, abs(float(u[dom]))))))
    return _LPS_DIR_TO_RFC4.get(key), deg


def analyze_dicom(path: str, name: str) -> DatasetResult:
    result = DatasetResult(name=name, path=path, kind="dicom")
    try:
        import pydicom
    except ImportError:
        result.add(SEV_INFO, "pydicom-missing", "install pydicom to analyze DICOM orientation")
        return result

    ds = pydicom.dcmread(path)
    patient_position = getattr(ds, "PatientPosition", None)
    iop = getattr(ds, "ImageOrientationPatient", None)
    if patient_position is not None:
        result.notes.append(f"PatientPosition={patient_position} (annotation only, NOT ground truth)")
    if iop is None:
        result.add(SEV_WARN, "no-iop", "ImageOrientationPatient (0020,0037) absent")
        return result

    iop = [float(x) for x in iop]
    # IOP is two direction cosines in patient LPS: the direction of increasing
    # column index (fast/x axis) and of increasing row index (y axis).
    fast = iop[0:3]     # image axis x (increasing column index)
    slow = iop[3:6]     # image axis y (increasing row index)
    normal = [          # slice axis z = fast x slow
        fast[1] * slow[2] - fast[2] * slow[1],
        fast[2] * slow[0] - fast[0] * slow[2],
        fast[0] * slow[1] - fast[1] * slow[0],
    ]
    result.notes.append(f"IOP={iop}")
    for axis_label, vec in (("x", fast), ("y", slow), ("z", normal)):
        rfc4, deg = _lps_to_rfc4(vec)
        if rfc4 is not None:
            result.axis_values[axis_label] = rfc4
        label = f"{axis_label}: {rfc4}"
        if rfc4 is not None and deg > OBLIQUE_DEG:
            label += f" (oblique, {deg:.0f}deg)"
            result.add(SEV_WARN, "not-roughly-aligned",
                       f"axis {axis_label} is {deg:.0f}deg off the nearest anatomical axis; "
                       f"the RFC-4 'roughly aligned' precondition may not hold")
        result.axes_summary.append(label)
    return result


# --------------------------------------------------------------------------- #
# Optional NRRD analysis (pynrrd)
# --------------------------------------------------------------------------- #

def _parse_space_letters(space: str) -> list[str] | None:
    """Parse an NRRD ``space`` field into 3 anatomical letters (e.g. LPS)."""
    words = space.lower().replace("-", " ").split()
    long_map = {"left": "L", "right": "R", "posterior": "P",
                "anterior": "A", "superior": "S", "inferior": "I"}
    if len(words) == 3 and all(w in long_map for w in words):
        return [long_map[w] for w in words]
    su = space.upper().replace("-", "")
    if len(su) == 3 and all(c in "LRPASI" for c in su):
        return list(su)
    return None


def analyze_nrrd(path: str, name: str) -> DatasetResult:
    result = DatasetResult(name=name, path=path, kind="nrrd")
    try:
        import nrrd
        import numpy as np
    except ImportError:
        result.add(SEV_INFO, "pynrrd-missing", "install pynrrd + numpy to analyze NRRD orientation")
        return result

    header = nrrd.read_header(path)
    space = header.get("space")
    directions = header.get("space directions")
    result.notes.append(f"space={space!r}")
    if space is None or directions is None:
        result.add(SEV_WARN, "no-space", "NRRD has no 'space' / 'space directions' header")
        return result

    letters = _parse_space_letters(space)
    if letters is None:
        result.add(SEV_WARN, "unknown-space", f"unrecognized NRRD space {space!r}")
        return result

    if header.get("measurement frame") is not None:
        result.notes.append("has a measurement frame (DWI/DTI); separate from RFC-4 orientation")

    # world (space) axis -> LPS unit contribution
    world_to_lps = np.array([_ANAT_LETTER_TO_LPS[c] for c in letters], dtype=float)
    for i, row in enumerate(np.asarray(directions, dtype=float)):
        if not np.any(np.isfinite(row)) or np.allclose(row, 0):
            result.axes_summary.append(f"{i}: (no direction)")
            continue
        lps = row @ world_to_lps            # direction in LPS world coords
        rfc4, deg = _lps_to_rfc4(lps)
        if rfc4 is not None:
            result.axis_values[str(i)] = rfc4
        label = f"{i}: {rfc4}"
        if rfc4 is not None and deg > OBLIQUE_DEG:
            label += f" (oblique, {deg:.0f}deg)"
            result.add(SEV_WARN, "not-roughly-aligned",
                       f"axis {i} is {deg:.0f}deg off the nearest anatomical axis; "
                       f"the RFC-4 'roughly aligned' precondition may not hold")
        result.axes_summary.append(label)
    return result


# --------------------------------------------------------------------------- #
# Ground-truth expectations for the RFC-4-Sample-Data dataset
# --------------------------------------------------------------------------- #

@dataclass
class Expectation:
    name: str
    kind: str
    relpaths: tuple[str, ...]          # candidate paths (first existing one is used)
    expect_valid: bool                 # should the dataset PASS RFC-4 validation?
    expected_orientations: dict[str, str] | None = None  # axis name -> value (ome-zarr only)
    description: str = ""


EXPECTATIONS: tuple[Expectation, ...] = (
    # Real ICBM152 brain -> OME-Zarr with orientation WRITTEN: the OME-Zarr
    # carrier of the standard A/P + I/S terms. Replaces the retired synthetic
    # TC-16/17 (LPS/RAS baselines); the subject-local TC-18/19/20 are now the
    # real datasets TC-24 skin / TC-44 airway / TC-25 heart.
    Expectation(
        "TC-49 real brain RAS (A/P + I/S)", "ome-zarr",
        ("ome-zarr/brain_icbm_ras.ome.zarr",),
        expect_valid=True,
        expected_orientations={"z": "inferior-to-superior", "y": "posterior-to-anterior",
                               "x": "left-to-right"},
        description="Real ICBM152 brain; standard A/P + I/S terms written into OME-Zarr",
    ),
    Expectation(
        "TC-50 real brain flipped (A/P + S/I)", "ome-zarr",
        ("ome-zarr/brain_icbm_ras_flip.ome.zarr",),
        expect_valid=True,
        expected_orientations={"z": "superior-to-inferior", "y": "anterior-to-posterior",
                               "x": "right-to-left"},
        description="Exact flip of TC-49; adds anterior-to-posterior + superior-to-inferior",
    ),
    Expectation(
        "TC-C invalid vocabulary", "ome-zarr",
        ("ome-zarr/TC-C_invalid_vocabulary.ome.zarr",),
        expect_valid=False,
        description="'LPS' shorthand is not in the vocabulary; MUST fail",
    ),
    Expectation(
        "TC-D orientation on time axis", "ome-zarr",
        ("ome-zarr/TC-D_orientation_on_time_axis.ome.zarr",),
        expect_valid=False,
        description="orientation on a type:time axis; MUST fail",
    ),
    Expectation(
        "TC-11 qform/sform mismatch", "nifti",
        ("nifti/TC-11_qform_sform_mismatch.nii.gz",),
        expect_valid=True,
        description="NIfTI conversion ambiguity (qform != sform)",
    ),
    Expectation(
        "TC-08 avg152 LR (MNI, LAS)", "nifti",
        ("nifti/avg152T1_LR_nifti.nii.gz",),
        expect_valid=True,
        description="MNI avg152 LR reference (neurological); flip pair with TC-09",
    ),
    Expectation(
        "TC-09 avg152 RL (MNI, RAS)", "nifti",
        ("nifti/avg152T1_RL_nifti.nii.gz",),
        expect_valid=True,
        description="MNI avg152 RL reference (radiological); proves L/R flip vs TC-08",
    ),
    Expectation(
        "TC-05 HFDR", "dicom",
        ("dicom/TC-05_HFDR.dcm",),
        expect_valid=True,
        description="Synthetic HFDR phantom (IOP=[0,-1,0,1,0,0])",
    ),
    Expectation(
        "TC-06 HFDL", "dicom",
        ("dicom/TC-06_HFDL.dcm",),
        expect_valid=True,
        description="Synthetic HFDL phantom (IOP=[0,1,0,-1,0,0])",
    ),
    # --- Stress cases (conformance/cases/, relative to the *repo*, not data-dir) ---
    Expectation(
        "SC-01 quadruped vocabulary", "ome-zarr",
        ("../conformance/cases/SC-01_quadruped_valid.ome.zarr",
         "conformance/cases/SC-01_quadruped_valid.ome.zarr"),
        expect_valid=True,
        expected_orientations={"z": "dorsal-to-ventral", "y": "rostral-to-caudal",
                               "x": "left-to-right"},
        description="Stress: quadruped terms must be accepted",
    ),
    Expectation(
        "SC-02 null orientation", "ome-zarr",
        ("../conformance/cases/SC-02_null_orientation.ome.zarr",
         "conformance/cases/SC-02_null_orientation.ome.zarr"),
        expect_valid=True,
        description="Stress: orientation:null == absent (warn, not error)",
    ),
    Expectation(
        "SC-03 orientation on channel", "ome-zarr",
        ("../conformance/cases/SC-03_channel_orientation.ome.zarr",
         "conformance/cases/SC-03_channel_orientation.ome.zarr"),
        expect_valid=False,
        description="Stress: orientation on a type:channel axis MUST fail",
    ),
    Expectation(
        "SC-04 oblique NIfTI", "nifti",
        ("../conformance/cases/SC-04_oblique_nifti.nii.gz",
         "conformance/cases/SC-04_oblique_nifti.nii.gz"),
        expect_valid=True,
        description="Stress: 30deg-oblique axes should trigger a 'roughly aligned' warning",
    ),
    Expectation(
        "SC-05 missing value", "ome-zarr",
        ("../conformance/cases/SC-05_missing_value.ome.zarr",
         "conformance/cases/SC-05_missing_value.ome.zarr"),
        expect_valid=False,
        description="Stress: orientation without a 'value' MUST fail",
    ),
    Expectation(
        "SC-06 bad type", "ome-zarr",
        ("../conformance/cases/SC-06_bad_type.ome.zarr",
         "conformance/cases/SC-06_bad_type.ome.zarr"),
        expect_valid=False,
        description="Stress: orientation.type != 'anatomical' MUST fail",
    ),
    Expectation(
        "SC-07 duplicate anatomical axis", "ome-zarr",
        ("../conformance/cases/SC-07_duplicate_pair.ome.zarr",
         "conformance/cases/SC-07_duplicate_pair.ome.zarr"),
        expect_valid=False,
        description="Stress: two axes on the same anatomical axis MUST fail",
    ),
    Expectation(
        "TC-13 MRHead (Slicer)", "nrrd",
        ("nrrd/MRHead.nrrd",),
        expect_valid=True,
        description="Real 3D Slicer brain MRI, NRRD LPS space (rotated axes)",
    ),
    # --- MINC + Analyze: derived via nibabel, exactly like NIfTI ---
    Expectation(
        "TC-26 ICBM152 T1 (MINC)", "minc",
        ("minc/mni_icbm152_t1.mnc",),
        expect_valid=True,
        description="Real MNI ICBM152 T1 brain (MINC2); nibabel axcodes SAR",
    ),
    Expectation(
        "TC-27 ICBM152 z-flip (MINC)", "minc",
        ("minc/icbm152_t1_2mm_zflip.mnc",),
        expect_valid=True,
        description="Reoriented ICBM152 (exact z-flip); superior-to-inferior on i",
    ),
    Expectation(
        "TC-28 ICBM152 xy-flip (MINC)", "minc",
        ("minc/icbm152_t1_2mm_xyflip.mnc",),
        expect_valid=True,
        description="Reoriented ICBM152 (exact x+y flip); right-to-left + anterior-to-posterior",
    ),
    Expectation(
        "TC-30 avg152T1 (Analyze)", "analyze",
        ("analyze/avg152T1.hdr",),
        expect_valid=True,
        description="Real SPM avg152T1 (Analyze 7.5); nibabel derives LAS (orientation ambiguous)",
    ),
    # --- Real OME-Zarr converted from real data via ngff-zarr (RFC-4 written) ---
    Expectation(
        "TC-21 mouse quadruped (Allen)", "ome-zarr",
        ("ome-zarr/mouse_allen_quadruped.ome.zarr",),
        expect_valid=True,
        expected_orientations={"z": "rostral-to-caudal", "y": "dorsal-to-ventral",
                               "x": "right-to-left"},
        description="Real Allen mouse brain (BrainGlobe, CC BY 4.0); quadruped vocabulary",
    ),
    Expectation(
        "TC-22 foot limb (TCIA CMB-MEL)", "ome-zarr",
        ("ome-zarr/foot_cmb_limb.ome.zarr",),
        expect_valid=True,
        expected_orientations={"z": "distal-to-proximal", "y": "dorsal-to-plantar"},
        description="Real foot CT (TCIA, CC BY 4.0); limb vocabulary (proximal-distal verified)",
    ),
    # --- Real oblique / DTI NIfTI (dcm_qa_canon_61, BSD-2-Clause, Chris Rorden) ---
    Expectation(
        "TC-23 Canon axial DTI (dcm_qa_canon_61)", "nifti",
        ("nifti/TC-23_canon_DTI_axial.nii.gz",),
        expect_valid=True,
        description="Real Canon 3T DTI, axial strict (0deg off-axis); clean LAS derivation (BSD-2)",
    ),
    Expectation(
        "TC-10 Canon oblique DTI (dcm_qa_canon_61)", "nifti",
        ("nifti/TC-10_canon_DTI_oblique_20d.nii.gz",),
        expect_valid=True,
        description="Real Canon 3T DTI, ~20deg on all views (36deg off-axis); MUST warn not-roughly-aligned (R8)",
    ),
    # --- Real subject-local EM (OpenOrganelle FIB-SEM, CC BY 4.0); depth axis only ---
    Expectation(
        "TC-24 skin superficial-to-deep (Janelia)", "ome-zarr",
        ("ome-zarr/skin_janelia_superficial_deep.ome.zarr",),
        expect_valid=True,
        expected_orientations={"z": "superficial-to-deep"},
        description="Real mouse skin FIB-SEM (jrc_mus-skin-1, CC BY 4.0); subject-local depth term (assigned)",
    ),
    Expectation(
        "TC-25 heart apex-to-base (cardiac MRI)", "ome-zarr",
        ("ome-zarr/heart_sunnybrook_apex_base.ome.zarr",),
        expect_valid=True,
        expected_orientations={"z": "apex-to-base"},
        description="Real cardiac short-axis cine MRI (Sunnybrook, CC0); apex-to-base, visually verifiable",
    ),
    Expectation(
        "TC-44 airway epithelium (apical-to-basal)", "ome-zarr",
        ("ome-zarr/airway_epithelium.ome.zarr",),
        expect_valid=True,
        expected_orientations={"z": "apical-to-basal"},
        description="Real human airway epithelium FIB-SEM (CC BY 4.0); apical marked by cilia",
    ),
    Expectation(
        "TC-46 whole-body mouse uCT (caudal-to-cranial)", "ome-zarr",
        ("ome-zarr/mouse_rosenhain_wholebody.ome.zarr",),
        expect_valid=True,
        expected_orientations={"z": "caudal-to-cranial", "y": "dorsal-to-ventral"},
        description="Real whole-body mouse micro-CT (Rosenhain, CC0); skull verified at cranial end",
    ),
    # --- Real OME-Zarr flips: reverse-direction terms via exact axis flips ---
    Expectation(
        "TC-39 Allen mouse flipped", "ome-zarr",
        ("ome-zarr/mouse_allen_quadruped_flip.ome.zarr",),
        expect_valid=True,
        expected_orientations={"z": "caudal-to-rostral", "y": "ventral-to-dorsal",
                               "x": "left-to-right"},
        description="Exact flip of TC-21; caudal-to-rostral + ventral-to-dorsal",
    ),
    Expectation(
        "TC-40 foot CT flipped", "ome-zarr",
        ("ome-zarr/foot_cmb_limb_flip.ome.zarr",),
        expect_valid=True,
        expected_orientations={"z": "proximal-to-distal", "y": "plantar-to-dorsal"},
        description="Exact flip of TC-22; proximal-to-distal + plantar-to-dorsal",
    ),
    Expectation(
        "TC-41 skin EM flipped", "ome-zarr",
        ("ome-zarr/skin_janelia_flip.ome.zarr",),
        expect_valid=True,
        expected_orientations={"z": "deep-to-superficial"},
        description="Exact flip of TC-24; deep-to-superficial",
    ),
    Expectation(
        "TC-42 cardiac MRI flipped", "ome-zarr",
        ("ome-zarr/heart_sunnybrook_flip.ome.zarr",),
        expect_valid=True,
        expected_orientations={"z": "base-to-apex"},
        description="Exact flip of TC-25; base-to-apex",
    ),
    Expectation(
        "TC-45 airway flipped", "ome-zarr",
        ("ome-zarr/airway_epithelium_flip.ome.zarr",),
        expect_valid=True,
        expected_orientations={"z": "basal-to-apical"},
        description="Exact flip of TC-44; basal-to-apical",
    ),
    Expectation(
        "TC-47 whole-body mouse flipped", "ome-zarr",
        ("ome-zarr/mouse_rosenhain_flip.ome.zarr",),
        expect_valid=True,
        expected_orientations={"z": "cranial-to-caudal", "y": "dorsal-to-ventral"},
        description="Exact flip of TC-46; cranial-to-caudal",
    ),
    # --- Vocabulary completion: hand palmar/dorsal (only pair with no open real data) ---
    Expectation(
        "VC-1 hand phantom (dorsal-to-palmar)", "ome-zarr",
        ("ome-zarr/vocab-quad-limb.ome.zarr",),
        expect_valid=True,
        expected_orientations={"z": "cranial-to-caudal", "y": "dorsal-to-palmar",
                               "x": "proximal-to-distal"},
        description="Synthetic hand phantom; palmar/dorsal are the only 2 terms with no open real dataset",
    ),
    Expectation(
        "VC-2 hand phantom flipped (palmar-to-dorsal)", "ome-zarr",
        ("ome-zarr/vocab-quad-limb-flip.ome.zarr",),
        expect_valid=True,
        expected_orientations={"z": "caudal-to-cranial", "y": "palmar-to-dorsal",
                               "x": "distal-to-proximal"},
        description="Exact flip of VC-1; palmar-to-dorsal",
    ),
    # --- Real DICOM (acquired, vs the synthetic HFDR/HFDL pair) ---
    Expectation(
        "TC-37 real CT axial (identity IOP)", "dicom",
        ("dicom/real_ct_small.dcm",),
        expect_valid=True,
        description="Real acquired DICOM; axial identity IOP; PatientPosition ignored",
    ),
    Expectation(
        "TC-48 real CT oblique (~22deg IOP)", "dicom",
        ("dicom/real_ct_oblique.dcm",),
        expect_valid=True,
        description="Real DICOM with non-identity oblique IOP; MUST warn not-roughly-aligned (R8)",
    ),
)


def check_expected_orientations(result: DatasetResult, expected: dict[str, str]) -> None:
    """Compare parsed orientations to ground truth (ome-zarr only)."""
    ome = load_ome_metadata(result.path)
    found: dict[str, str] = {}
    if ome and isinstance(ome.get("multiscales"), list):
        for ms in ome["multiscales"]:
            for ax in ms.get("axes", []):
                orient = ax.get("orientation")
                if isinstance(orient, dict) and "value" in orient:
                    found[ax.get("name", "?")] = orient["value"]
    for axis, want in expected.items():
        got = found.get(axis)
        if got != want:
            result.add(SEV_ERROR, "wrong-orientation",
                       f"axis '{axis}': expected {want!r}, found {got!r}")


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #

def _resolve_input(relpaths: tuple[str, ...], data_dir: str) -> str | None:
    """Find a case input under the sample-data dir OR the repo (for conformance
    fixtures that ship with the code, e.g. conformance/cases/)."""
    for rp in relpaths:
        for base in (data_dir, REPO_ROOT):
            cand = os.path.join(base, rp)
            if os.path.exists(cand):
                return cand
    return None


def run(data_dir: str) -> list[DatasetResult]:
    results: list[DatasetResult] = []
    for exp in EXPECTATIONS:
        path = _resolve_input(exp.relpaths, data_dir)
        if path is None:
            r = DatasetResult(name=exp.name, path=exp.relpaths[0], kind=exp.kind)
            r.expect_valid = exp.expect_valid
            r.add(SEV_WARN, "missing-file", f"none of {exp.relpaths} found under {data_dir}")
            r.expectation_met = None
            results.append(r)
            continue

        if exp.kind == "ome-zarr":
            r = validate_ome_zarr(path, exp.name)
            if exp.expect_valid and exp.expected_orientations:
                check_expected_orientations(r, exp.expected_orientations)
        elif exp.kind == "nifti":
            r = analyze_nifti(path, exp.name)
        elif exp.kind == "dicom":
            r = analyze_dicom(path, exp.name)
        elif exp.kind == "nrrd":
            r = analyze_nrrd(path, exp.name)
        elif exp.kind == "minc":
            r = analyze_minc(path, exp.name)
        elif exp.kind == "analyze":
            r = analyze_analyze(path, exp.name)
        else:
            r = DatasetResult(name=exp.name, path=path, kind=exp.kind)

        r.expect_valid = exp.expect_valid
        r.notes.insert(0, exp.description)

        # Decide whether the expectation was met.
        if exp.kind == "ome-zarr":
            r.expectation_met = (r.is_rfc4_valid == exp.expect_valid)
        else:
            # NIfTI/DICOM are advisory: met unless the analyzer raised an ERROR.
            r.expectation_met = not r.errors
        results.append(r)
    return results


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

_COLOR = sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def print_report(results: list[DatasetResult]) -> None:
    print(_c("RFC-4 OME-NGFF orientation validation", "1"))
    print("=" * 72)
    for r in results:
        if r.expectation_met is None:
            status = _c("SKIP", "33")
        elif r.expectation_met:
            status = _c("PASS", "32")
        else:
            status = _c("FAIL", "31")
        expect = "expect valid" if r.expect_valid else "expect INVALID"
        print(f"\n[{status}] {r.name}  ({r.kind}, {expect})")
        for note in r.notes:
            if note:
                print(f"       · {note}")
        for label in r.axes_summary:
            print(f"       axis {label}")
        for issue in r.issues:
            if issue.severity == SEV_ERROR:
                marker = _c("ERROR", "31")
            elif issue.severity == SEV_WARN:
                marker = _c("WARN", "33")
            else:
                marker = _c("INFO", "36")
            print(f"       {marker} [{issue.code}] {issue.message}")

    passed = sum(1 for r in results if r.expectation_met is True)
    failed = sum(1 for r in results if r.expectation_met is False)
    skipped = sum(1 for r in results if r.expectation_met is None)
    print("\n" + "=" * 72)
    print(f"Total {len(results)}  ·  {_c(str(passed) + ' passed', '32')}  ·  "
          f"{_c(str(failed) + ' failed', '31' if failed else '0')}  ·  {skipped} skipped")


def to_json(results: list[DatasetResult]) -> dict:
    return {
        "results": [
            {
                "name": r.name,
                "kind": r.kind,
                "path": r.path,
                "expect_valid": r.expect_valid,
                "rfc4_valid": r.is_rfc4_valid if r.kind == "ome-zarr" else None,
                "expectation_met": r.expectation_met,
                "axes": r.axes_summary,
                "notes": r.notes,
                "issues": [{"severity": i.severity, "code": i.code, "message": i.message}
                           for i in r.issues],
            }
            for r in results
        ],
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r.expectation_met is True),
            "failed": sum(1 for r in results if r.expectation_met is False),
            "skipped": sum(1 for r in results if r.expectation_met is None),
        },
    }


def to_canonical(result: DatasetResult) -> dict:
    """The canonical per-input conformance output (see conformance/manifest.yaml).

    A conformant RFC-4 tool, given one input path, emits exactly this shape. This
    is what the conformance driver (conformance/run_conformance.py) diffs against
    the manifest's authored ground truth.
    """
    return {
        "input": result.path,
        "format": result.kind,
        # rfc4_valid is meaningful only for OME-Zarr schema cases; derived formats
        # (DICOM / NIfTI / NRRD) carry no schema to validate, so they report null.
        "rfc4_valid": (result.is_rfc4_valid if result.kind == "ome-zarr" else None),
        "axes": result.axis_values,
        "violations": [i.code for i in result.issues if i.severity == SEV_ERROR],
        "warnings": [i.code for i in result.issues if i.severity == SEV_WARN],
    }


_FORMAT_BY_EXT = {".dcm": "dicom", ".nrrd": "nrrd", ".nhdr": "nrrd", ".nii": "nifti",
                  ".mnc": "minc", ".hdr": "analyze", ".img": "analyze"}


def detect_format(path: str) -> str:
    """Guess the input format from its path (extension / zarr layout)."""
    low = path.rstrip("/").lower()
    if low.endswith(".nii.gz") or low.endswith(".nii"):
        return "nifti"
    _, ext = os.path.splitext(low)
    if ext in _FORMAT_BY_EXT:
        return _FORMAT_BY_EXT[ext]
    return "ome-zarr"  # .zarr / .ome.zarr / .zip / a plain directory


def analyze_input(path: str, fmt: str | None = None) -> DatasetResult:
    """Run the right analyzer for one input and return its DatasetResult."""
    fmt = fmt or detect_format(path)
    name = os.path.basename(path.rstrip("/"))
    if fmt == "ome-zarr":
        return validate_ome_zarr(path, name)
    if fmt == "nifti":
        return analyze_nifti(path, name)
    if fmt == "dicom":
        return analyze_dicom(path, name)
    if fmt == "nrrd":
        return analyze_nrrd(path, name)
    if fmt == "minc":
        return analyze_minc(path, name)
    if fmt == "analyze":
        return analyze_analyze(path, name)
    r = DatasetResult(name=name, path=path, kind=fmt)
    r.add(SEV_ERROR, "unknown-format", f"cannot analyze format {fmt!r}")
    return r


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate OME-Zarr RFC-4 orientation metadata.")
    parser.add_argument("--data-dir", default="RFC-4-Sample-Data",
                        help="path to the RFC-4-Sample-Data directory (default: %(default)s)")
    parser.add_argument("--json", metavar="FILE", help="also write a JSON report to FILE")
    parser.add_argument("--emit-canonical", metavar="INPUT",
                        help="analyze ONE dataset and print its canonical conformance JSON, then exit "
                             "(this is the CLI the conformance driver calls)")
    parser.add_argument("--format", choices=["ome-zarr", "nifti", "dicom", "nrrd", "minc", "analyze"],
                        help="override format detection for --emit-canonical")
    args = parser.parse_args(argv)

    if args.emit_canonical:
        result = analyze_input(args.emit_canonical, args.format)
        print(json.dumps(to_canonical(result), indent=2))
        return 0

    if not os.path.isdir(args.data_dir):
        # Not fatal: the sample data may live elsewhere (Hugging Face). Cases
        # under it will be skipped; conformance fixtures shipped with the code
        # (conformance/cases/) still run. Use `python fetch_data.py` to get data.
        print(f"note: sample-data dir not found: {args.data_dir} "
              f"(run fetch_data.py); running conformance fixtures only", file=sys.stderr)

    results = run(args.data_dir)
    print_report(results)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(to_json(results), fh, indent=2)
        print(f"\nJSON report written to {args.json}")

    return 0 if all(r.expectation_met in (True, None) for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
