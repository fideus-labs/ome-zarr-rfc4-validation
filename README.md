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
uv run python fetch_data.py                                  # get data from HF
uv run python conformance/generate_stress_cases.py           # (optional) regenerate the SC-* fixtures (already shipped)
uv run python validate_rfc4.py --data-dir hf-data
uv run python test_validate_rfc4.py --data-dir hf-data
uv run python conformance/run_conformance.py --data-dir hf-data   # drive a tool's CLI vs the manifest
```

(Prefer pip? `python -m venv .venv && .venv/bin/pip install -r requirements.txt` still works.)

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

Reference validator: **26/26** cases. Proof suite: **141** checks. Conformance
driver (`conformance/run_conformance.py`): drives any tool's CLI against the
manifest and diffs its canonical output — the reference validator passes 26/26
through it (`--emit-canonical` is the CLI it calls).

Next: land the `ngff-zarr conformance` subcommand (see
[conformance/NGFF_ZARR_CONFORMANCE.md](conformance/NGFF_ZARR_CONFORMANCE.md)) so
ngff-zarr becomes a verified validator passing this suite.
