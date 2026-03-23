"""
Build a volumetric 3D mesh from a 2D image silhouette.

Extracts the foreground shape, computes depth from distance-to-edge
(thicker at center, thin at boundary), then builds a closed mesh with
front face, back face, and side walls — a proper solid, not a flat plane.
"""

from __future__ import annotations

from collections import Counter

import numpy as np
import trimesh
from numpy.typing import NDArray
from PIL import Image
from scipy.ndimage import binary_erosion, binary_fill_holes, distance_transform_edt
from scipy.spatial import Delaunay


def _extract_foreground_mask(image: Image.Image) -> NDArray[np.bool_]:
    """Separate foreground from background using alpha or edge-color thresholding.

    If the image has an alpha channel with **real** transparency (>5% of pixels transparent),
    use it directly.  Otherwise fall back to edge-color thresholding — handles RGBA images
    that are fully opaque (common with AI-generated or web-sourced PNGs).
    """
    arr = np.array(image)

    if arr.ndim == 3 and arr.shape[2] == 4:
        alpha = arr[:, :, 3]
        transparent_frac = float(np.count_nonzero(alpha <= 128)) / max(alpha.size, 1)
        if transparent_frac > 0.05:
            return alpha > 128

    gray = np.array(image.convert("L"), dtype=np.float64)

    edges = np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])
    bg_mean = float(np.mean(edges))
    bg_std = max(float(np.std(edges)), 8.0)
    threshold = max(bg_std * 1.5, 20.0)

    mask = np.abs(gray - bg_mean) > threshold
    mask = binary_fill_holes(mask)
    return mask


def _boundary_edges_ordered(faces: NDArray[np.int64]) -> list[tuple[int, int]]:
    """Return boundary half-edges with winding consistent with the face they came from."""
    edge_faces: dict[tuple[int, int], int] = {}
    for f in faces:
        for i in range(3):
            a, b = int(f[i]), int(f[(i + 1) % 3])
            canonical = (min(a, b), max(a, b))
            if canonical in edge_faces:
                edge_faces[canonical] = -1  # interior (shared)
            else:
                edge_faces[canonical] = 0
                # Store directed half-edge in a separate dict
    # Re-scan to get directed boundary half-edges
    half_counts: Counter[tuple[int, int]] = Counter()
    for f in faces:
        for i in range(3):
            a, b = int(f[i]), int(f[(i + 1) % 3])
            half_counts[(a, b)] += 1
    boundary: list[tuple[int, int]] = []
    for (a, b), count in half_counts.items():
        canonical = (min(a, b), max(a, b))
        if edge_faces.get(canonical) == 0:
            if count == 1:
                boundary.append((a, b))
    return boundary


def _subsample_mask(mask: NDArray[np.bool_], max_res: int) -> NDArray[np.bool_]:
    h, w = mask.shape
    if max(h, w) <= max_res:
        return mask
    ratio = max_res / max(h, w)
    new_h = max(4, int(round(h * ratio)))
    new_w = max(4, int(round(w * ratio)))
    im = Image.fromarray(mask.astype(np.uint8) * 255, mode="L")
    im = im.resize((new_w, new_h), Image.Resampling.NEAREST)
    return np.array(im) > 128


def _mask_bbox_slices(mask: NDArray[np.bool_], pad: int = 2) -> tuple[slice, slice] | None:
    """Return ``(row_slice, col_slice)`` for the foreground bounding box, or ``None`` if empty."""
    if not np.any(mask):
        return None
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    if not np.any(rows) or not np.any(cols):
        return None
    ry = np.where(rows)[0]
    cx = np.where(cols)[0]
    r0, r1 = int(ry[0]), int(ry[-1]) + 1
    c0, c1 = int(cx[0]), int(cx[-1]) + 1
    h, w = mask.shape
    r0 = max(0, r0 - pad)
    r1 = min(h, r1 + pad)
    c0 = max(0, c0 - pad)
    c1 = min(w, c1 + pad)
    if r1 <= r0 or c1 <= c0:
        return None
    return np.s_[r0:r1], np.s_[c0:c1]


def _tight_bbox_crop(mask: NDArray[np.bool_], pad: int = 2) -> NDArray[np.bool_]:
    """
    Crop to the foreground bounding box so orthographic views share **subject** scale.

    Large empty margins on the **side** image were stretching depth in the voxel hull and
    making the result look **paper-thin from the front** or mis-angled vs the profile.
    """
    sl = _mask_bbox_slices(mask, pad)
    if sl is None:
        return mask
    sy, sx = sl
    out = mask[sy, sx]
    return out.copy() if out.size else mask


def _resize_gray_to_shape(gray: NDArray[np.float64], shape: tuple[int, int]) -> NDArray[np.float64]:
    """Resize float grayscale ``(H,W)`` in ``[0,1]`` to ``shape`` (h, w) with LANCZOS."""
    th, tw = shape
    gh, gw = gray.shape
    if (gh, gw) == (th, tw):
        return gray
    im = Image.fromarray((np.clip(gray, 0.0, 1.0) * 255).astype(np.uint8), mode="L")
    im = im.resize((tw, th), Image.Resampling.LANCZOS)
    return np.asarray(im, dtype=np.float64) / 255.0


def _to_grayscale_float(image: Image.Image) -> NDArray[np.float64]:
    gray = image.convert("L")
    return np.asarray(gray, dtype=np.float64) / 255.0


def mesh_from_pil_image(
    image: Image.Image,
    *,
    max_resolution: int = 128,
    plane_scale: float = 1.0,
    height_scale: float = 0.35,
    vertical_asym: float = 0.0,
    gray_depth: float = 0.0,
) -> trimesh.Trimesh:
    """
    Image → solid volumetric mesh (front + back + side walls).

    ``height_scale`` controls thickness from the silhouette (distance transform).
    ``vertical_asym`` shifts thickness with image row (top vs bottom) — rough
    front/back separation along the view axis.
    ``gray_depth`` uses luminance as a weak depth cue (brighter = more forward).
    """
    im = image.convert("RGBA") if image.mode == "RGBA" else image.convert("RGB")

    mask_full = _extract_foreground_mask(im)
    mask = _subsample_mask(mask_full, max_resolution)
    mask = binary_fill_holes(mask)

    # Erode 1 px to avoid stray single-pixel borders
    eroded = binary_erosion(mask, iterations=1)
    if eroded.sum() > 20:
        mask = eroded

    gray_full = _to_grayscale_float(im)
    mh, mw = mask.shape
    if gray_full.shape != (mh, mw):
        gimg = Image.fromarray((np.clip(gray_full, 0.0, 1.0) * 255).astype(np.uint8), mode="L")
        gimg = gimg.resize((mw, mh), Image.Resampling.LANCZOS)
        gray = np.asarray(gimg, dtype=np.float64) / 255.0
    else:
        gray = gray_full

    dist = distance_transform_edt(mask).astype(np.float64)
    max_dist = float(dist.max())
    if max_dist < 1.0:
        raise ValueError(
            "Could not separate foreground from background. "
            "Use an image with a clear subject on a contrasting background."
        )
    dist /= max_dist

    ys, xs = np.where(mask)
    if len(ys) < 10:
        raise ValueError("Too few foreground pixels detected.")

    img_h, img_w = mask.shape

    x_norm = ((xs / img_w) - 0.5) * float(plane_scale)
    z_norm = ((ys / img_h) - 0.5) * float(plane_scale)
    scale = float(plane_scale)
    depth = dist[ys, xs] * float(height_scale) * scale
    row_norm = (ys.astype(np.float64) / float(img_h)) - 0.5
    g = gray[ys, xs]
    g_bias = (g - 0.5) * 2.0
    bias = float(vertical_asym) * row_norm * scale + float(gray_depth) * scale * g_bias
    y_front = depth + bias
    y_back = -depth + bias

    # --- front (+Y) and back (−Y) vertices ---
    front_verts = np.column_stack([x_norm, y_front, z_norm])
    back_verts = np.column_stack([x_norm, y_back, z_norm])
    n = len(front_verts)
    all_verts = np.vstack([front_verts, back_verts])

    # --- Delaunay on the 2D projection ---
    pts2d = np.column_stack([x_norm, z_norm])
    tri = Delaunay(pts2d)

    # Filter triangles whose centroid falls outside the mask
    centroids = pts2d[tri.simplices].mean(axis=1)
    cx_px = np.clip(((centroids[:, 0] / float(plane_scale)) + 0.5) * img_w, 0, img_w - 1).astype(np.intp)
    cz_px = np.clip(((centroids[:, 1] / float(plane_scale)) + 0.5) * img_h, 0, img_h - 1).astype(np.intp)
    valid = mask[cz_px, cx_px]

    # Delaunay winding is CW from +Y; reverse front so normals point outward (+Y)
    front_faces = tri.simplices[valid][:, ::-1]
    back_faces = tri.simplices[valid] + n

    # --- side walls from boundary edges ---
    # Use directed half-edges so side-wall winding is consistent with the front face
    boundary = _boundary_edges_ordered(front_faces)
    side_faces_list: list[list[int]] = []
    for a, b in boundary:
        # Front edge goes a→b (outward-facing); side wall connects front to back
        side_faces_list.append([b, a, a + n])
        side_faces_list.append([b, a + n, b + n])

    side_faces = np.array(side_faces_list, dtype=np.int64) if side_faces_list else np.empty((0, 3), dtype=np.int64)
    all_faces = np.vstack([front_faces, back_faces, side_faces])

    mesh = trimesh.Trimesh(vertices=all_verts, faces=all_faces, process=True)
    mesh.fix_normals()
    return mesh
