#!/usr/bin/env python3
"""Convert the two REAL downloaded volumes to OME-Zarr with RFC-4 orientation,
using the reference implementation (ngff-zarr).

  mouse_allen_quadruped.ome.zarr  (Allen mouse brain, BrainGlobe; CC BY 4.0)
      quadruped terms: z=rostral-to-caudal, y=dorsal-to-ventral, x=right-to-left
      (from the atlas 'asr' orientation code)

  foot_cmb_limb.ome.zarr  (TCIA CMB-MEL foot CT; CC BY 4.0)
      limb terms: z=distal-to-proximal (VERIFIED by bone-mass: heel/proximal at high z),
                  y=dorsal-to-plantar (assigned; standard supine positioning),
                  x omitted (medial-lateral has no RFC-4 term)
"""
import glob
import os
import sys

import numpy as np
import tifffile
import pydicom
import dask.array as da
import ngff_zarr as nz
from ngff_zarr import AnatomicalOrientation, AnatomicalOrientationValues as V

SP = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(SP, "real-out")
os.makedirs(OUT, exist_ok=True)


def _o(val):
    return AnatomicalOrientation(value=val)


def write(name, data, scale, orientations):
    data = np.ascontiguousarray(data)
    img = nz.NgffImage(
        data=da.from_array(data, chunks=data.shape),
        dims=("z", "y", "x"),
        scale=scale,
        translation={"z": 0.0, "y": 0.0, "x": 0.0},
        axes_orientations=orientations,
    )
    ms = nz.to_multiscales(img, scale_factors=[])  # single scale, keep it light
    path = os.path.join(OUT, name)
    try:
        nz.to_ngff_zarr(path, ms, enabled_rfcs=[4])
    except TypeError:
        nz.to_ngff_zarr(path, ms)  # older/newer signature
    print(f"wrote {path}  shape={data.shape} dtype={data.dtype}")
    for d in ("z", "y", "x"):
        if d in orientations:
            print(f"   {d}: {orientations[d].value.value}")


def mouse(tiff_path):
    vol = tifffile.imread(tiff_path)  # (132, 80, 114) uint16, orientation 'asr'
    write("mouse_allen_quadruped.ome.zarr", vol,
          {"z": 0.1, "y": 0.1, "x": 0.1},  # 100 micron -> mm
          {"z": _o(V.rostral_to_caudal), "y": _o(V.dorsal_to_ventral),
           "x": _o(V.right_to_left)})


def foot(dicom_dir):
    ds = [pydicom.dcmread(f) for f in glob.glob(os.path.join(dicom_dir, "*.dcm"))]
    ds.sort(key=lambda d: float(d.ImagePositionPatient[2]))  # ascending z
    vol = np.stack([d.pixel_array.astype(np.int16) for d in ds])  # (83, 512, 512) z,y,x
    vol = vol[:, ::4, ::4]  # in-plane downsample x4 -> keep the sample light
    write("foot_cmb_limb.ome.zarr", vol,
          {"z": 3.0, "y": 0.316 * 4, "x": 0.316 * 4},
          {"z": _o(V.distal_to_proximal), "y": _o(V.dorsal_to_plantar)})  # x omitted


if __name__ == "__main__":
    mouse(os.path.join(SP, "allen100", "allen_mouse_100um_v1.2", "reference.tiff"))
    foot(os.path.join(SP, "bone_axial"))
