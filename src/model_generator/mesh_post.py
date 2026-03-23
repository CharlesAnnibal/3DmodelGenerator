"""Shared mesh fixes before GLB export (Unity orientation, optional smoothing)."""

from __future__ import annotations

import math
import os

import trimesh
import trimesh.transformations as tt


def apply_export_orientation(mesh: trimesh.Trimesh) -> None:
    """
    Unity glTF import often shows meshes **inverted on Y** (feet/head swapped in world Y).

    **Default:** scale **(1, −1, 1)** — mirrors across the XZ plane without the old **Rx(180°)**
    that also flipped **Z** and confused facing.

    **Alternate:** set ``MODEL_GENERATOR_UNITY_YAW_180=1`` for a **180° rotation about Y**
    (swaps left/right and front/back, leaves Y-up).

    Set ``MODEL_GENERATOR_NO_UNITY_ROTATE=1`` to skip.
    """
    if os.environ.get("MODEL_GENERATOR_NO_UNITY_ROTATE", "").strip().lower() in ("1", "true", "yes"):
        return
    if os.environ.get("MODEL_GENERATOR_UNITY_YAW_180", "").strip().lower() in ("1", "true", "yes"):
        mesh.apply_transform(tt.rotation_matrix(math.pi, [0.0, 1.0, 0.0]))
        return
    mesh.apply_scale([1.0, -1.0, 1.0])


def apply_export_smoothing(mesh: trimesh.Trimesh) -> None:
    """
    Mild Laplacian smoothing to reduce blocky marching-cubes / silhouette facets.

    ``MODEL_GENERATOR_SMOOTH_ITER`` — default ``6``; set ``0`` to disable.
    """
    raw = os.environ.get("MODEL_GENERATOR_SMOOTH_ITER", "6").strip()
    if not raw:
        return
    try:
        n = int(raw)
    except ValueError:
        return
    if n <= 0:
        return
    trimesh.smoothing.filter_laplacian(mesh, lamb=0.22, iterations=min(n, 30))
