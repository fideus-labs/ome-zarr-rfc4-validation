# ome-zarr-rfc4-validation

Reference validator and **conformance suite** for OME-Zarr
**RFC-4 (axis anatomical orientation)** —
[spec](https://ngff.openmicroscopy.org/rfc/4) ·
[ome/ngff#528](https://github.com/ome/ngff/pull/528).

RFC-4 adds one optional field to *spatial* axes (`type: "space"`):

```json
{ "name": "x", "type": "space",
  "orientation": { "type": "anatomical", "value": "left-to-right" } }
```

`value` is one of **24 controlled-vocabulary** directions naming the axis's
lowest→highest coordinate direction.

> **Data lives elsewhere.** The test images are in the Hugging Face repo
> [`fideus-labs/ome-zarr-rfc4-data`](https://huggingface.co/fideus-labs/ome-zarr-rfc4-data).
> This repo holds only code. Run `python fetch_data.py` to pull the data into `./hf-data`.

## Contents

```
validate_rfc4.py         reference validator (stdlib for OME-Zarr; nibabel/pydicom/pynrrd optional)
test_validate_rfc4.py    proof suite: positive + adversarial + manifest parity
fetch_data.py            clone the sample data from Hugging Face
conformance/
  manifest.yaml          the tool-agnostic suite: every case + the RFC-4 rule it tests + expected output
  orientation.schema.json JSON Schema for the orientation object (24-term enum)
  build_manifest.py      regenerates manifest.yaml + the schema, prints the coverage matrix
  generate_stress_cases.py  generates the SC-* boundary cases (conformance/cases/)
  README.md              the conformance model, canonical output contract, coverage table
```

## Quickstart

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python fetch_data.py                                  # get data from HF
.venv/bin/python conformance/generate_stress_cases.py           # regenerate SC-* fixtures
.venv/bin/python validate_rfc4.py --data-dir hf-data
.venv/bin/python test_validate_rfc4.py --data-dir hf-data
```

`validate_rfc4.py` exits 0 when every case meets its expectation. The proof suite
additionally injects broken metadata and asserts it is **rejected with the right
error code**, and checks the validator's output against `conformance/manifest.yaml`.

## What it checks

- **OME-Zarr** (normative, stdlib): orientation only on `space` axes; `{type, value}`
  present; `type == "anatomical"`; `value` in the 24-term vocabulary; one direction
  per anatomical axis; `null` flagged (SHOULD omit).
- **NIfTI / DICOM / NRRD** (optional): derives orientation from the affine /
  `ImageOrientationPatient` / NRRD `space directions`, and warns when axes are
  oblique (the RFC-4 "roughly aligned" precondition).

See [conformance/README.md](conformance/README.md) for the requirement-coverage
matrix (every rule R1–R10 exercised, no redundant case).

## Status

Reference validator passes 22/22 cases; proof suite 99/99 checks.
Roadmap: a `run_conformance.py` driver that shells out to any tool's CLI
(starting with an `ngff-zarr --validate-rfc4` mode) and diffs its canonical
output against the manifest.
