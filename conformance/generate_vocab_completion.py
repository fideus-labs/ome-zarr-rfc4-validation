#!/usr/bin/env python3
"""Generate tiny synthetic OME-Zarr phantoms that cover every RFC-4 vocabulary
term not already present in real/synthetic data, so the corpus reaches 24/24.

Terms are packed into phantoms greedily: at most one direction per anatomical
axis (pair) per phantom, up to 3 space axes each.
"""
import glob
import os
import sys

import numpy as np
import dask.array as da
import ngff_zarr as nz
from ngff_zarr import AnatomicalOrientation, AnatomicalOrientationValues as V

import validate_rfc4 as VAL

DATA = sys.argv[1] if len(sys.argv) > 1 else "RFC-4-Sample-Data"
OUT = os.path.join(DATA, "synthetic", "ome-zarr")


def covered_terms():
    used = set()
    for p in glob.glob(os.path.join(DATA, "**", "*.ome.zarr"), recursive=True):
        ome = VAL.load_ome_metadata(p)
        if not ome:
            continue
        for ms in ome.get("multiscales", []):
            for a in ms.get("axes", []):
                o = a.get("orientation")
                if isinstance(o, dict) and o.get("value"):
                    used.add(o["value"])
    return used


def pack(missing):
    """Greedy: list of phantoms, each a list of (dim, term) with distinct pairs."""
    remaining = list(missing)
    phantoms = []
    while remaining:
        used_pairs, chosen, leftover = set(), [], []
        for term in remaining:
            pair = VAL._VALUE_TO_PAIR[term]
            if pair not in used_pairs and len(chosen) < 3:
                used_pairs.add(pair)
                chosen.append(term)
            else:
                leftover.append(term)
        phantoms.append(chosen)
        remaining = leftover
    return phantoms


def write(name, terms):
    dims = ("z", "y", "x")[: len(terms)]
    shape = (8,) * len(terms)
    data = np.zeros(shape, dtype=np.float32)
    data[(0,) * len(terms)] = 1.0
    img = nz.NgffImage(
        data=da.from_array(data, chunks=shape),
        dims=dims,
        scale={d: 1.0 for d in dims},
        translation={d: 0.0 for d in dims},
        axes_orientations={d: AnatomicalOrientation(value=V(t)) for d, t in zip(dims, terms)},
    )
    ms = nz.to_multiscales(img, scale_factors=[])
    path = os.path.join(OUT, name)
    try:
        nz.to_ngff_zarr(path, ms, enabled_rfcs=[4])
    except TypeError:
        nz.to_ngff_zarr(path, ms)
    print(f"  {name}: {terms}")


def main():
    missing = sorted(set(VAL.ANATOMICAL_VOCABULARY) - covered_terms())
    print(f"{len(missing)} terms missing -> packing")
    for i, terms in enumerate(pack(missing), 1):
        write(f"vocab-completion-{i}.ome.zarr", terms)


if __name__ == "__main__":
    main()
