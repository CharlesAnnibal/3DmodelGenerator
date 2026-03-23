"""Orchestrate: image → mesh → GLB file."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from model_generator.export_glb import export_glb
from model_generator.mesh_from_image import mesh_from_pil_image
from model_generator.mesh_from_two_views import mesh_from_front_side
from model_generator.paths import reference_model_path
from model_generator.reference_mesh import load_reference_mesh


def generate_glb_from_image(
    image: Image.Image,
    output_path: str | Path,
    *,
    side_image: Image.Image | None = None,
    max_resolution: int = 128,
    plane_scale: float = 1.0,
    height_scale: float = 0.35,
    vertical_asym: float = 0.0,
    gray_depth: float = 0.0,
    mirror_side: bool = False,
    hull_rounding: float = 0.35,
    top_image: Image.Image | None = None,
    back_image: Image.Image | None = None,
    bottom_image: Image.Image | None = None,
) -> Path:
    """
    Build a GLB mesh:

    * **Reference on disk** → load reference geometry, apply ``plane_scale``,
      export directly (images ignored for geometry).
    * **Side image provided** → **multi-view visual hull** (front + side + optional top /
      back / bottom). ``gray_depth`` becomes ``hull_gray_depth``: front **luminance** sculpts
      depth (eyes/nose). Optional views carve **top/bottom** (plan) and **back** without mirroring
      the **front** silhouette. ``mirror_side`` only duplicates the **side** mask along depth
      (optional; default off).
    * **Otherwise** → single-image volumetric silhouette with optional **vertical_asym**
      and **gray_depth** cues.
    """
    ref = reference_model_path()
    if ref is not None:
        mesh = load_reference_mesh(ref)
        mesh.apply_scale(float(plane_scale))
    elif side_image is not None:
        mesh = mesh_from_front_side(
            image,
            side_image,
            top_image=top_image,
            back_image=back_image,
            bottom_image=bottom_image,
            voxel_resolution=max_resolution,
            plane_scale=plane_scale,
            mirror_side=mirror_side,
            hull_gray_depth=float(gray_depth),
            hull_rounding=float(hull_rounding),
        )
    else:
        mesh = mesh_from_pil_image(
            image,
            max_resolution=max_resolution,
            plane_scale=plane_scale,
            height_scale=height_scale,
            vertical_asym=vertical_asym,
            gray_depth=gray_depth,
        )
    return export_glb(mesh, output_path)


def reference_status_message() -> str:
    p = reference_model_path()
    if p is None:
        return (
            "Reference mesh: **none** — use **one image** (silhouette mesh) or **front + side** "
            "for a 3D visual hull. Put optional `reference.glb` in `reference/` only if you "
            "want to copy that model."
        )
    return f"Reference mesh: **`{p.name}`** — output copies that geometry (scaled). Images ignored."
