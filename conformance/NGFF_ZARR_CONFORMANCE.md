# Making `ngff-zarr` a verified RFC-4 validator

Goal (from the RFC-4 conformance plan): add a `conformance` subcommand to
[`ngff-zarr`](https://github.com/thewtex/ngff-zarr) so it becomes one of the
*verified validators* that pass this suite. The driver
([`run_conformance.py`](run_conformance.py)) already drives any tool; ngff-zarr
just needs to speak the canonical contract.

## The contract

`ngff-zarr conformance <input>` must read one dataset and print **exactly** this
JSON to stdout (see `manifest.yaml → canonical_output_contract`):

```json
{
  "input": "<path>",
  "format": "ome-zarr",
  "rfc4_valid": true,
  "axes": { "z": "inferior-to-superior", "y": "anterior-to-posterior", "x": "right-to-left" },
  "violations": [],
  "warnings": []
}
```

- `rfc4_valid`: `true`/`false` for OME-Zarr schema cases; `null` for derived
  formats (DICOM/NIfTI/NRRD) that carry no OME-Zarr schema.
- `axes`: map of axis name → the RFC-4 orientation value (omit axes with none).
- `violations` / `warnings`: lists of *codes* (see the table below). A code may
  appear once per offending axis; the driver checks the expected set is a subset.

## Violation / warning codes the suite expects

| code | when |
|---|---|
| `orientation-on-non-space` | orientation on a `time`/`channel` axis (R1) |
| `missing-value` | orientation object without `value` (R2) |
| `bad-type` | `orientation.type != "anatomical"` (R3) |
| `bad-value` | value not in the 24-term vocabulary (R4) |
| `duplicate-anatomical-axis` | two axes on the same antonym pair (R5) |
| `null-orientation` *(warning)* | `orientation: null` — SHOULD omit (R6) |
| `not-roughly-aligned` *(warning)* | axis > 15° off the nearest anatomical axis (R8) |

## Reference implementation sketch

`ngff-zarr` already models RFC-4 (`AnatomicalOrientation`,
`AnatomicalOrientationValues`), so the subcommand is mostly a read + check + print.
A minimal version (adapt to ngff-zarr's CLI framework — it uses `argparse`):

```python
import json, sys
import ngff_zarr as nz
from ngff_zarr import AnatomicalOrientationValues as V

VOCAB = {v.value for v in V}          # the 24 canonical terms

def conformance(input_path: str) -> dict:
    ms = nz.from_ngff_zarr(input_path)          # -> Multiscales
    axes = ms.metadata.axes
    out_axes, violations, warnings = {}, [], []
    seen_pairs = {}
    for ax in axes:
        orient = getattr(ax, "orientation", None)
        if orient is None:
            continue
        if ax.type != "space":
            violations.append("orientation-on-non-space")
        value = getattr(orient, "value", None)
        value = getattr(value, "value", value)   # enum -> str
        if value is None:
            violations.append("missing-value"); continue
        if getattr(orient, "type", "anatomical") != "anatomical":
            violations.append("bad-type")
        if value not in VOCAB:
            violations.append("bad-value"); continue
        out_axes[ax.name] = value
        # R5: one direction per anatomical axis
        pair = frozenset({value, _antonym(value)})
        if pair in seen_pairs:
            violations.append("duplicate-anatomical-axis")
        seen_pairs[pair] = ax.name
    return {
        "input": input_path, "format": "ome-zarr",
        "rfc4_valid": not violations,
        "axes": out_axes, "violations": violations, "warnings": warnings,
    }

# CLI: ngff-zarr conformance <input>
if __name__ == "__main__":
    print(json.dumps(conformance(sys.argv[1]), indent=2))
```

(For DICOM/NIfTI/NRRD, emit `rfc4_valid: null` and derive `axes` from the affine /
IOP / space directions — ngff-zarr already does this conversion internally when it
reads those via ITK; expose the derived orientation the same way.)

## Run the suite against it

Once the subcommand exists:

```bash
python conformance/run_conformance.py \
    --data-dir ../ome-zarr-rfc4-data \
    --tool "ngff-zarr conformance {input}"
```

Exit code 0 ⟺ ngff-zarr conforms on every case. That is the check to add to
ngff-zarr's CI, and the evidence that it is a verified RFC-4 validator.
