#!/usr/bin/env python3
"""Fetch a light (s7) level of two OpenOrganelle FIB-SEM volumes and write them
as OME-Zarr with RFC-4 subject-local orientation. Depth axis only is annotated
(in-plane axes have no anatomical meaning); the depth term is ASSIGNED from
sample-prep knowledge, not derived -> needs_manual_verification.

  jrc_mus-skin-1  -> z = superficial-to-deep   (CC BY 4.0, Janelia/HHMI)
  jrc_mus-heart-1 -> z = apex-to-base          (CC BY 4.0, Janelia/HHMI)
"""
import json
import os

import numpy as np
import s3fs
import zarr
import dask.array as da
import ngff_zarr as nz
from ngff_zarr import AnatomicalOrientation, AnatomicalOrientationValues as V

import sys
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "ome-zarr-rfc4-data", "real", "ome-zarr")
LEVEL = "s7"
fs = s3fs.S3FileSystem(anon=True)


SCRATCH = os.path.dirname(os.path.abspath(__file__))


def fetch(ds):
    grp = f"janelia-cosem-datasets/{ds}/{ds}.zarr/recon-1/em/fibsem-uint8"
    attrs = json.loads(fs.cat(f"{grp}/.zattrs"))
    ms = attrs["multiscales"][0]
    axes = [a["name"] for a in ms["axes"]]           # ('z','y','x')
    dset = next(d for d in ms["datasets"] if d["path"] == LEVEL)
    scale = dset["coordinateTransformations"][0]["scale"]  # per-axis, in nm
    # download the small s7 level locally (sync s3fs; avoids zarr-v3/async loop clash)
    local = os.path.join(SCRATCH, f"{ds}_{LEVEL}")
    fs.get(f"{grp}/{LEVEL}", local, recursive=True)
    arr = zarr.open_array(local, mode="r", zarr_format=2)
    data = np.asarray(arr[:])
    return data, dict(zip(axes, scale))


def write(name, data, scale_nm, orientations):
    data = np.ascontiguousarray(data)
    scale_um = {k: v / 1000.0 for k, v in scale_nm.items()}  # nm -> micrometer
    img = nz.NgffImage(
        data=da.from_array(data, chunks=data.shape),
        dims=("z", "y", "x"),
        scale=scale_um,
        translation={"z": 0.0, "y": 0.0, "x": 0.0},
        axes_units={"z": "micrometer", "y": "micrometer", "x": "micrometer"},
        axes_orientations=orientations,
    )
    ms = nz.to_multiscales(img, scale_factors=[])
    path = os.path.join(OUT, name)
    try:
        nz.to_ngff_zarr(path, ms, enabled_rfcs=[4])
    except TypeError:
        nz.to_ngff_zarr(path, ms)
    print(f"wrote {path}  shape={data.shape} dtype={data.dtype} scale_um={scale_um}")
    for d, o in orientations.items():
        print(f"   {d}: {o.value.value}")


if __name__ == "__main__":
    skin, s_scale = fetch("jrc_mus-skin-1")
    write("skin_janelia_superficial_deep.ome.zarr", skin, s_scale,
          {"z": AnatomicalOrientation(value=V.superficial_to_deep)})

    heart, h_scale = fetch("jrc_mus-heart-1")
    write("heart_janelia_apex_base.ome.zarr", heart, h_scale,
          {"z": AnatomicalOrientation(value=V.apex_to_base)})
