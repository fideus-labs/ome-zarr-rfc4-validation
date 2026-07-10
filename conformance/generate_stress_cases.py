#!/usr/bin/env python3
"""Generate the RFC-4 *stress* conformance cases that the sample dataset lacks.

The shipped RFC-4-Sample-Data covers the happy paths and two negatives (TC-C,
TC-D). These extra cases push the boundaries of the spec so the conformance
suite genuinely stress-tests an implementation rather than only confirming it:

  SC-01_quadruped_valid   valid  vocab coverage: quadruped terms
                                 (dorsal-to-ventral / rostral-to-caudal)
  SC-02_null_orientation  valid  SHOULD: orientation:null == absent (warn, not error)
  SC-03_channel_orient    INVALID MUST: orientation on a type:channel axis is forbidden
  SC-04_oblique_nifti     valid* precondition: axes NOT roughly aligned -> tool SHOULD warn

Each OME-Zarr store is written as a minimal, loadable Zarr v3 group (raw
little-endian codec, one chunk) so the metadata is real, not a stub.
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np


def write_ome_zarr(store: str, axes: list[dict], shape: tuple[int, ...]) -> None:
    """Write a minimal Zarr v3 OME-NGFF 0.5 store with the given axes."""
    dims = [ax["name"] for ax in axes]
    root = {
        "attributes": {
            "ome": {
                "version": "0.5",
                "multiscales": [{
                    "axes": axes,
                    "datasets": [{
                        "path": "scale0/image",
                        "coordinateTransformations": [
                            {"type": "scale", "scale": [1.0] * len(shape)},
                            {"type": "translation", "translation": [0.0] * len(shape)},
                        ],
                    }],
                    "name": "image",
                }],
            }
        },
        "zarr_format": 3,
        "node_type": "group",
    }
    array_meta = {
        "shape": list(shape),
        "data_type": "float32",
        "chunk_grid": {"name": "regular", "configuration": {"chunk_shape": list(shape)}},
        "chunk_key_encoding": {"name": "default", "configuration": {"separator": "/"}},
        "fill_value": 0.0,
        "codecs": [{"name": "bytes", "configuration": {"endian": "little"}}],
        "attributes": {"_ARRAY_DIMENSIONS": dims},
        "dimension_names": dims,
        "zarr_format": 3,
        "node_type": "array",
    }
    image_dir = os.path.join(store, "scale0", "image")
    os.makedirs(image_dir, exist_ok=True)
    with open(os.path.join(store, "zarr.json"), "w") as fh:
        json.dump(root, fh, indent=2)
    with open(os.path.join(store, "scale0", "zarr.json"), "w") as fh:
        json.dump({"attributes": {"_ARRAY_DIMENSIONS": dims}, "zarr_format": 3, "node_type": "group"}, fh, indent=2)
    with open(os.path.join(image_dir, "zarr.json"), "w") as fh:
        json.dump(array_meta, fh, indent=2)
    # one raw chunk (single-chunk grid -> key c/0/0/0[/0])
    data = np.zeros(shape, dtype="<f4")
    data[tuple(slice(0, max(1, s // 2)) for s in shape)] = 1.0
    chunk_path = os.path.join(image_dir, "c", *(["0"] * len(shape)))
    os.makedirs(os.path.dirname(chunk_path), exist_ok=True)
    with open(chunk_path, "wb") as fh:
        fh.write(data.tobytes())


def _anat(value: str) -> dict:
    return {"type": "anatomical", "value": value}


def gen_quadruped(base: str) -> None:
    write_ome_zarr(
        os.path.join(base, "SC-01_quadruped_valid.ome.zarr"),
        [
            {"name": "z", "type": "space", "orientation": _anat("dorsal-to-ventral")},
            {"name": "y", "type": "space", "orientation": _anat("rostral-to-caudal")},
            {"name": "x", "type": "space", "orientation": _anat("left-to-right")},
        ],
        (16, 16, 16),
    )


def gen_null(base: str) -> None:
    write_ome_zarr(
        os.path.join(base, "SC-02_null_orientation.ome.zarr"),
        [
            {"name": "z", "type": "space", "orientation": None},
            {"name": "y", "type": "space", "orientation": _anat("anterior-to-posterior")},
            {"name": "x", "type": "space", "orientation": _anat("right-to-left")},
        ],
        (16, 16, 16),
    )


def gen_channel(base: str) -> None:
    write_ome_zarr(
        os.path.join(base, "SC-03_channel_orientation.ome.zarr"),
        [
            # 'dorsal-to-ventral' is unused by the space axes, so this isolates the
            # single violation under test (orientation on a non-space axis) without
            # also tripping the one-direction-per-anatomical-axis rule.
            {"name": "c", "type": "channel", "orientation": _anat("dorsal-to-ventral")},
            {"name": "z", "type": "space", "orientation": _anat("inferior-to-superior")},
            {"name": "y", "type": "space", "orientation": _anat("anterior-to-posterior")},
            {"name": "x", "type": "space", "orientation": _anat("right-to-left")},
        ],
        (2, 16, 16, 16),
    )


def gen_missing_value(base: str) -> None:
    write_ome_zarr(
        os.path.join(base, "SC-05_missing_value.ome.zarr"),
        [
            {"name": "z", "type": "space", "orientation": {"type": "anatomical"}},  # no value
            {"name": "y", "type": "space", "orientation": _anat("anterior-to-posterior")},
            {"name": "x", "type": "space", "orientation": _anat("right-to-left")},
        ],
        (16, 16, 16),
    )


def gen_bad_type(base: str) -> None:
    write_ome_zarr(
        os.path.join(base, "SC-06_bad_type.ome.zarr"),
        [
            {"name": "z", "type": "space",
             "orientation": {"type": "geographical", "value": "inferior-to-superior"}},
            {"name": "y", "type": "space", "orientation": _anat("anterior-to-posterior")},
            {"name": "x", "type": "space", "orientation": _anat("right-to-left")},
        ],
        (16, 16, 16),
    )


def gen_duplicate_pair(base: str) -> None:
    write_ome_zarr(
        os.path.join(base, "SC-07_duplicate_pair.ome.zarr"),
        [
            {"name": "z", "type": "space", "orientation": _anat("inferior-to-superior")},
            {"name": "y", "type": "space", "orientation": _anat("left-to-right")},
            {"name": "x", "type": "space", "orientation": _anat("right-to-left")},  # collides with y
        ],
        (16, 16, 16),
    )


def gen_oblique_nifti(base: str) -> None:
    import nibabel as nib
    data = np.zeros((16, 16, 16), dtype=np.int16)
    data[:8] = 100
    theta = np.radians(30.0)  # 30 deg -> well beyond "roughly aligned"
    c, s = np.cos(theta), np.sin(theta)
    affine = np.array([
        [-c, -s, 0, 0],
        [s, -c, 0, 0],
        [0,  0, 1, 0],
        [0,  0, 0, 1],
    ], dtype=float)
    img = nib.Nifti1Image(data, affine=affine)
    img.header.set_qform(affine, code=1)
    img.header.set_sform(affine, code=1)
    nib.save(img, os.path.join(base, "SC-04_oblique_nifti.nii.gz"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", default="conformance/cases")
    args = ap.parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    gen_quadruped(args.output_dir)
    gen_null(args.output_dir)
    gen_channel(args.output_dir)
    gen_missing_value(args.output_dir)
    gen_bad_type(args.output_dir)
    gen_duplicate_pair(args.output_dir)
    gen_oblique_nifti(args.output_dir)
    print(f"stress cases written to {args.output_dir}/")


if __name__ == "__main__":
    main()
