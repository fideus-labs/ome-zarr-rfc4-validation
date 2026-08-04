# ome-zarr-rfc4-validation

Reference validator and **conformance suite** for OME-Zarr
**RFC-4 (axis anatomical orientation)** —
[spec](https://ngff.openmicroscopy.org/rfc/4).

RFC-4 adds one optional field to *spatial* axes (`type: "space"`):

```json
{ "name": "x", "type": "space",
  "orientation": { "type": "anatomical", "value": "left-to-right" } }
```

`value` is one of **24 controlled-vocabulary** directions naming the axis's
lowest→highest coordinate direction. The field is optional per axis: an axis
with no anatomical direction is left unannotated.

> **Data lives elsewhere.** The test images are in the Hugging Face repo
> [`fideus-labs/ome-zarr-rfc4-data`](https://huggingface.co/fideus-labs/ome-zarr-rfc4-data),
> also mirrored to a public S3 bucket at
> [`ome-zarr-rfc4.s3.filebase.io`](https://ome-zarr-rfc4.s3.filebase.io) (Filebase).
> This repo holds only code. Pull the data into `./hf-data` with
> `python fetch_data.py` (from Hugging Face) or
> `python fetch_data.py --source s3` (from the S3 mirror, no credentials).

## Contents

```
validate_rfc4.py         reference validator (stdlib for OME-Zarr; nibabel/pydicom/pynrrd optional)
test_validate_rfc4.py    proof suite: positive + adversarial + manifest parity
fetch_data.py            clone the sample data from Hugging Face
conformance/
  manifest.yaml          the tool-agnostic suite: every case + the RFC-4 rule it tests + expected output
  run_conformance.py     drives ANY tool's CLI against the manifest, diffs its canonical output
  orientation.schema.json JSON Schema for the orientation object (24-term enum)
  build_manifest.py      regenerates manifest.yaml + the schema, prints the coverage matrix
  generate_stress_cases.py  generates the SC-* boundary cases (conformance/cases/)
  NGFF_ZARR_CONFORMANCE.md  how to make ngff-zarr a verified validator (the `conformance` subcommand)
  README.md              the conformance model, canonical output contract, coverage table
```

## Quickstart

Uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync                                                      # env from pyproject.toml + uv.lock
uv run python fetch_data.py                                  # get data from Hugging Face
# or  uv run python fetch_data.py --source s3                #   ... from the Filebase S3 mirror (no credentials)
uv run python conformance/generate_stress_cases.py           # (optional) regenerate the SC-* fixtures (already shipped)
uv run python validate_rfc4.py --data-dir hf-data
uv run python test_validate_rfc4.py --data-dir hf-data
uv run python conformance/run_conformance.py --data-dir hf-data   # drive a tool's CLI vs the manifest
```

(Prefer pip? `python -m venv .venv && .venv/bin/pip install -r requirements.txt` still works.)

## Download from the S3 mirror

The sample data is mirrored to a public [Filebase](https://filebase.com) S3
bucket, readable **without credentials** — handy if you cannot use `git-lfs` or
want only part of the corpus:

```bash
# a single file over plain HTTP
curl -O https://ome-zarr-rfc4.s3.filebase.io/manifest.csv

# the whole corpus via the anonymous S3 API (endpoint https://s3.filebase.io)
s5cmd --no-sign-request --endpoint-url=https://s3.filebase.io sync 's3://ome-zarr-rfc4/*' ./hf-data/
# or with the AWS CLI
aws --no-sign-request --endpoint-url=https://s3.filebase.io s3 sync s3://ome-zarr-rfc4 ./hf-data
```

The bucket mirrors the Hugging Face repo (the source of truth); it is kept in
sync by [`.github/workflows/sync-filebase.yml`](.github/workflows/sync-filebase.yml).

`validate_rfc4.py` exits 0 when every case meets its expectation. The proof suite
additionally injects broken metadata and asserts it is **rejected with the right
error code**, and checks the validator's output against `conformance/manifest.yaml`.

## What it checks

- **OME-Zarr** (normative, stdlib): orientation only on `space` axes; `{type, value}`
  present; `type == "anatomical"`; `value` in the 24-term vocabulary; one direction
  per anatomical axis; `null` flagged (SHOULD omit).
- **NIfTI / MINC / Analyze / DICOM / NRRD** (optional): derives orientation from
  the affine (NIfTI/MINC/Analyze, via nibabel) / `ImageOrientationPatient` (DICOM) /
  NRRD `space directions`, and warns when axes are oblique (the RFC-4 "roughly
  aligned" precondition).

See [conformance/README.md](conformance/README.md) for the requirement-coverage
matrix (every rule R1–R10 exercised, no redundant case).

## The dataset

- **38 cases** across 9 formats: OME-Zarr, DICOM, NIfTI, NRRD, MINC, Analyze,
  Bruker ParaVision, Varian FDF, whole-slide imaging (Aperio SVS).
- **30 real, 8 synthetic.** **36 valid, 2 invalid** (must-reject).
- All **24 vocabulary terms** are present. `palmar`/`dorsal` appear only in the
  synthetic hand phantom; the other 22 appear in real data.
- All 24 terms appear as written OME-Zarr `orientation` metadata; for the
  source-format files the orientation is derived from the native header
  (DICOM IOP, NIfTI affine, NRRD space directions, MINC direction cosines).

Every case is indexed in the data repo's `manifest.csv`: `test_id, format, path,
category, expect, rfc4_rules, orientation, data, source, license, notes`.

Orientation is listed per axis in lowest→highest coordinate order; `—` marks an
axis left unannotated (no applicable RFC-4 term).

### OME-Zarr — orientation written in the metadata

| ID | File | Orientation | Data | License |
|---|---|---|---|---|
| TC-21 | `ome-zarr/mouse_allen_quadruped.ome.zarr` | z rostral-to-caudal · y dorsal-to-ventral · x right-to-left | real | CC BY 4.0 |
| TC-39 | `ome-zarr/mouse_allen_quadruped_flip.ome.zarr` | z caudal-to-rostral · y ventral-to-dorsal · x left-to-right | real | CC BY 4.0 |
| TC-22 | `ome-zarr/foot_cmb_limb.ome.zarr` | z distal-to-proximal · y dorsal-to-plantar · x — | real | CC BY 4.0 |
| TC-40 | `ome-zarr/foot_cmb_limb_flip.ome.zarr` | z proximal-to-distal · y plantar-to-dorsal · x — | real | CC BY 4.0 |
| TC-24 | `ome-zarr/skin_janelia_superficial_deep.ome.zarr` | z superficial-to-deep · y — · x — | real | CC BY 4.0 |
| TC-41 | `ome-zarr/skin_janelia_flip.ome.zarr` | z deep-to-superficial · y — · x — | real | CC BY 4.0 |
| TC-25 | `ome-zarr/heart_sunnybrook_apex_base.ome.zarr` | z apex-to-base · y — · x — | real | CC0 1.0 |
| TC-42 | `ome-zarr/heart_sunnybrook_flip.ome.zarr` | z base-to-apex · y — · x — | real | CC0 1.0 |
| TC-44 | `ome-zarr/airway_epithelium.ome.zarr` | z apical-to-basal · y — · x — | real | CC BY 4.0 |
| TC-45 | `ome-zarr/airway_epithelium_flip.ome.zarr` | z basal-to-apical · y — · x — | real | CC BY 4.0 |
| TC-46 | `ome-zarr/mouse_rosenhain_wholebody.ome.zarr` | z caudal-to-cranial · y dorsal-to-ventral · x — | real | CC0 |
| TC-47 | `ome-zarr/mouse_rosenhain_flip.ome.zarr` | z cranial-to-caudal · y dorsal-to-ventral · x — | real | CC0 |
| TC-49 | `ome-zarr/brain_icbm_ras.ome.zarr` | z inferior-to-superior · y posterior-to-anterior · x left-to-right | real | MNI |
| TC-50 | `ome-zarr/brain_icbm_ras_flip.ome.zarr` | z superior-to-inferior · y anterior-to-posterior · x right-to-left | real | MNI |
| VC-1 | `ome-zarr/vocab-quad-limb.ome.zarr` | z cranial-to-caudal · y dorsal-to-palmar · x proximal-to-distal | synthetic | CC0 |
| VC-2 | `ome-zarr/vocab-quad-limb-flip.ome.zarr` | z caudal-to-cranial · y palmar-to-dorsal · x distal-to-proximal | synthetic | CC0 |

**Invalid (must be rejected):**

| ID | File | Violation | Code |
|---|---|---|---|
| TC-C | `ome-zarr/TC-C_invalid_vocabulary.ome.zarr` | `LPS` is not one of the 24 terms | `bad-value` |
| TC-D | `ome-zarr/TC-D_orientation_on_time_axis.ome.zarr` | orientation on a `type: "time"` axis | `orientation-on-non-space` |

### Source formats — orientation derived from the native header

| ID | File | Orientation | Data | License |
|---|---|---|---|---|
| TC-05 | `dicom/TC-05_HFDR.dcm` | x posterior-to-anterior · y right-to-left · z inferior-to-superior | synthetic | CC0 |
| TC-06 | `dicom/TC-06_HFDL.dcm` | x anterior-to-posterior · y left-to-right · z inferior-to-superior | synthetic | CC0 |
| TC-37 | `dicom/real_ct_small.dcm` | x right-to-left · y anterior-to-posterior · z inferior-to-superior | real | pydicom test data |
| TC-48 | `dicom/real_ct_oblique.dcm` | x right-to-left · y anterior-to-posterior · z inferior-to-superior | real | pydicom test data |
| TC-08 | `nifti/avg152T1_LR_nifti.nii.gz` | i right-to-left · j posterior-to-anterior · k inferior-to-superior | real | public domain |
| TC-09 | `nifti/avg152T1_RL_nifti.nii.gz` | i left-to-right · j posterior-to-anterior · k inferior-to-superior | real | public domain |
| TC-10 | `nifti/TC-10_canon_DTI_oblique_20d.nii.gz` | i right-to-left · j posterior-to-anterior · k inferior-to-superior | real | BSD-2-Clause |
| TC-23 | `nifti/TC-23_canon_DTI_axial.nii.gz` | i right-to-left · j posterior-to-anterior · k inferior-to-superior | real | BSD-2-Clause |
| TC-11 | `nifti/TC-11_qform_sform_mismatch.nii.gz` | i right-to-left · j posterior-to-anterior · k inferior-to-superior | synthetic | CC0 |
| TC-13 | `nrrd/MRHead.nrrd` | 0 anterior-to-posterior · 1 superior-to-inferior · 2 left-to-right | real | donated, no restrictions |
| TC-26 | `minc/mni_icbm152_t1.mnc` | xspace left-to-right · yspace posterior-to-anterior · zspace inferior-to-superior | real | MNI |
| TC-27 | `minc/icbm152_t1_2mm_zflip.mnc` | xspace left-to-right · yspace posterior-to-anterior · zspace superior-to-inferior | real | MNI |
| TC-28 | `minc/icbm152_t1_2mm_xyflip.mnc` | xspace right-to-left · yspace anterior-to-posterior · zspace inferior-to-superior | real | MNI |
| TC-30 | `analyze/avg152T1.hdr` | i right-to-left · j posterior-to-anterior · k inferior-to-superior | real | BSD-3-Clause |
| TC-31 | `bruker/PV6.0_FLASH` | read left-to-right · phase dorsal-to-ventral · slice rostral-to-caudal | real | Apache-2.0 |
| TC-34 | `bruker/rat_PV5.1/9` | read left-to-right · phase dorsal-to-ventral · slice rostral-to-caudal | real | CC BY 4.0 |
| TC-36 | `bruker/human_PV5.1` | axis0 right-to-left · axis1 superior-to-inferior · axis2 posterior-to-anterior | real | CC BY 4.0 |
| TC-32 | `fdf/test.fdf` | — (no patient position; geometric `orientation[]` only) | real | Apache-2.0 |
| TC-33 | `fdf/synthetic_HFS_supine.fdf` | x left-to-right · y posterior-to-anterior · z inferior-to-superior | synthetic | CC0 |
| TC-38 | `wsi/CMU-1-Small-Region.svs` | z superficial-to-deep · y — · x — | real | OpenSlide testdata |

Full per-source licensing and attribution is in the
[data repo README](https://huggingface.co/fideus-labs/ome-zarr-rfc4-data).

## Screenshots

### Derived orientation overlays

Three-panel axial/coronal/sagittal views with L/R/A/P/S/I markers, rendered from
the file's own header via nibabel/ITK. One per case, 35 total in
`screenshots/derived/`.

![TC-49 brain_icbm_ras](https://huggingface.co/fideus-labs/ome-zarr-rfc4-data/resolve/main/screenshots/derived/TC-49_brain_icbm_ras_markers.png)

![TC-13 MRHead](https://huggingface.co/fideus-labs/ome-zarr-rfc4-data/resolve/main/screenshots/derived/TC-13_MRHead_markers.png)

A flip pair renders as mirrored markers — TC-49 above, and its exact axis-flip:

![TC-50 brain_icbm_ras_flip](https://huggingface.co/fideus-labs/ome-zarr-rfc4-data/resolve/main/screenshots/derived/TC-50_brain_icbm_ras_flip_markers.png)

### Viewers

The same files opened in four viewers: 3D Slicer (13 captures), ITK-SNAP (8),
NiiVue (14), napari (18).

![TC-13 MRHead in 3D Slicer](https://huggingface.co/fideus-labs/ome-zarr-rfc4-data/resolve/main/screenshots/slicer/TC-13_MRHead.png)

![TC-26 ICBM152 T1 in ITK-SNAP](https://huggingface.co/fideus-labs/ome-zarr-rfc4-data/resolve/main/screenshots/itksnap/TC-26_mni_icbm152_t1.png)

![TC-08 avg152T1 LR in NiiVue](https://huggingface.co/fideus-labs/ome-zarr-rfc4-data/resolve/main/screenshots/niivue/TC-08_avg152T1_LR_nifti.png)

![TC-49 brain_icbm_ras in napari](https://huggingface.co/fideus-labs/ome-zarr-rfc4-data/resolve/main/screenshots/napari/TC-49_brain_icbm_ras.png)

napari reads the OME-Zarr but does not apply the RFC-4 `orientation` field; its
axis labels are the axis names, not anatomical directions.

## Conformance testing

`conformance/run_conformance.py` drives **any** tool's CLI against
`conformance/manifest.yaml` and diffs its output. The tool must read one dataset
and print this JSON to stdout:

```json
{
  "input": "<path>",
  "format": "ome-zarr",
  "rfc4_valid": true,
  "axes": { "z": "inferior-to-superior", "y": "posterior-to-anterior", "x": "left-to-right" },
  "violations": [],
  "warnings": []
}
```

`rfc4_valid` is `true`/`false` for OME-Zarr, `null` for derived formats that
carry no OME-Zarr schema. `axes` maps axis name → RFC-4 value, omitting
unannotated axes. `violations`/`warnings` are code lists.

### With ngff-zarr

[`ngff-zarr`](https://github.com/thewtex/ngff-zarr) exposes this contract through
a `conformance` subcommand
([PR #605](https://github.com/fideus-labs/ngff-zarr/pull/605)):

```bash
ngff-zarr conformance hf-data/ome-zarr/brain_icbm_ras.ome.zarr
```

Drive the whole suite through it:

```bash
uv run python conformance/run_conformance.py \
    --data-dir hf-data \
    --tool "ngff-zarr conformance {input}"
```

Exit code 0 means the tool matched the expected verdict on every case. The same
driver runs the reference validator:

```bash
uv run python conformance/run_conformance.py \
    --data-dir hf-data \
    --tool "python validate_rfc4.py --emit-canonical {input}"
```

Restrict to one format with `--format ome-zarr`; write a machine-readable report
with `--json report.json`.

See [conformance/NGFF_ZARR_CONFORMANCE.md](conformance/NGFF_ZARR_CONFORMANCE.md)
for the full contract and a reference implementation sketch.

### Violation and warning codes

| Code | Condition | Rule |
|---|---|---|
| `orientation-on-non-space` | orientation on a `time`/`channel` axis | R1 |
| `missing-value` | orientation object without `value` | R2 |
| `bad-type` | `orientation.type != "anatomical"` | R3 |
| `bad-value` | value not in the 24-term vocabulary | R4 |
| `duplicate-anatomical-axis` | two axes on the same antonym pair | R5 |
| `null-orientation` *(warning)* | `orientation: null` — SHOULD omit | R6 |
| `not-roughly-aligned` *(warning)* | axis > 15° off the nearest anatomical axis | R8 |

## Status

Reference validator: **39/39** cases. Proof suite: **194** checks. Conformance
driver (`conformance/run_conformance.py`): drives any tool's CLI against the
manifest and diffs its canonical output — the reference validator passes 39/39
through it (`--emit-canonical` is the CLI it calls).
