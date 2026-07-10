# RFC-4 Conformance Suite

A **tool-agnostic** conformance suite for OME-Zarr RFC-4 (axis anatomical
orientation). It follows the spec-conformance pattern: *test data* + a
*canonical output contract* + a *driver* that feeds each dataset to any
implementation's CLI and compares its output to the expected ground truth.

```
conformance/
├── manifest.yaml            <- the formal suite: every case + which RFC-4 rule it tests + expected output
├── build_manifest.py        <- regenerates manifest.yaml and prints the coverage matrix
├── generate_stress_cases.py <- generates the SC-* boundary cases below
└── cases/                   <- the stress datasets (the happy-path data lives in the ome-zarr-rfc4-data repo)
```

## Why each case exists (traceability, not decoration)

Every case is tied to a normative requirement, so the suite is **justified** and
**non-redundant** — when two cases share a coordinate system they exercise a
*different layer* (metadata schema vs geometry derivation).

| Req | Level | What it checks | Cases |
|-----|-------|----------------|-------|
| R1 | MUST | orientation only on `space` axes | TC-D (time), SC-03 (channel) |
| R2 | MUST | `{type, value}` both present | TC-16 (+), SC-05 (−) |
| R3 | MUST | `type == "anatomical"` | TC-16 (+), SC-06 (−) |
| R4 | MUST | `value` in the 24-term vocabulary | TC-16 (+), TC-C (−) |
| R5 | MUST | one direction per anatomical axis | SC-07 |
| R6 | SHOULD | `null` == absent (warn, don't error) | SC-02 |
| R7 | DEF | value = lowest→highest direction (flip) | TC-16/17, TC-08/09, TC-06 |
| R8 | SHOULD | roughly aligned (oblique → warn) | SC-04 (30° NIfTI), TC-13 (rotated NRRD) |
| R9 | COVER | full vocab incl. PR#528 + quadruped | TC-18/19/20, SC-01 |
| R10 | DERIVE | correct derivation from DICOM/NIfTI/NRRD | TC-05/06, TC-11, TC-08/09, TC-13/14/15 |

Run `python conformance/build_manifest.py` to print the live coverage matrix —
it asserts **every requirement is covered** and **no case is orphaned**.

## Stress cases (`cases/`)

Boundary cases the happy-path dataset lacks, so the suite pushes the spec rather
than only confirming it. Regenerate with `python conformance/generate_stress_cases.py`.

| Case | Expect | Stresses |
|------|--------|----------|
| SC-01 quadruped | valid | quadruped terms accepted (R9) |
| SC-02 null orientation | valid + warn | null == absent (R6) |
| SC-03 orientation on channel | **invalid** | non-space rule, channel variant (R1) |
| SC-04 oblique NIfTI (30°) | valid + warn | roughly-aligned precondition (R8) |
| SC-05 missing value | **invalid** | required fields (R2) |
| SC-06 bad type | **invalid** | type must be anatomical (R3) |
| SC-07 duplicate pair | **invalid** | one direction per axis (R5) |

## Canonical output contract

A conformant tool, given one input, emits (per `manifest.yaml`):

```json
{
  "input": "…/TC-16_synthetic_LPS.ome.zarr",
  "format": "ome-zarr",
  "rfc4_valid": true,
  "axes": [{"name": "z", "type": "space", "orientation": "inferior-to-superior"}, …],
  "violations": [],
  "warnings": []
}
```

`violations[].code` and `warnings[].code` are the stable identifiers the driver
compares against `manifest.yaml`'s `expected` (e.g. `orientation-on-non-space`,
`bad-value`, `null-orientation`, `not-roughly-aligned`).

## Reference implementation

[`../validate_rfc4.py`](../validate_rfc4.py) is the reference validator/adapter and
passes every case (`python validate_rfc4.py` → 21/21). The next step is a
`run_conformance.py` driver that shells out to *any* tool's CLI (starting with a
`ngff-zarr --validate-rfc4` mode) and diffs its canonical output against the
manifest — so an implementation can prove it passes its own conformance suite.

The community JS [`ome-ngff-validator`](https://github.com/ome/ome-ngff-validator)
is a second target adapter.
