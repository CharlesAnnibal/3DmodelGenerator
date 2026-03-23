"""
Multi-view visual hull: intersect silhouettes from **front**, **side**, and optionally
**top**, **back**, and **bottom** (Y-up, Unity-friendly).

- **Front** (−Z): columns = +X, rows = +Y
- **Side** (−X): columns = +Z (depth), rows = +Y
- **Top** (−Y, bird’s eye): rows = Z, cols = X (resize to match side×front extent)
- **Back** (+Z): same layout as **front**; voxel X is **flipped** when sampling (opposite camera)
- **Bottom** (+Y): same grid as **top**

``mirror_side`` mirrors only the **side** mask along depth (Z in the side image) — it does
**not** mirror the front silhouette. Default **False**; use only if you want a symmetric
**lateral** profile without a second side photo.

**Preprocessing:** foreground masks are **tight-cropped** by default so empty canvas on the
**side** view does not squash depth in the hull. Set ``MODEL_GENERATOR_NO_BBOX_CROP=1`` to
disable. Optional leg tweaks: ``MODEL_GENERATOR_TOP_BOTTOM_ERODE=1``,
``MODEL_GENERATOR_VOXEL_OPEN=1`` (aggressive; can flatten the mesh).

**Face / ears:** Pure silhouettes fill each column in depth — use ``hull_gray_depth`` (front
luminance) for eye/nose read; **ears** need a **top** plan where ears stick out.

**Length / plan:** Voxel spacing follows **(wf, hf, ws)** mask sizes so body **length** (side
depth ``ws``) is not squashed vs width. **Top** and **bottom** try **original vs transposed**
resize and pick the orientation that tightens the hull (fixes wrong axis for creature length).
Set ``MODEL_GENERATOR_NO_AUTO_PLAN_SWAP=1`` to always use the doc orientation only.
"""

from __future__ import annotations

import os

import numpy as np
import trimesh
from numpy.typing import NDArray
from PIL import Image
from scipy.ndimage import binary_erosion, binary_opening, distance_transform_edt, gaussian_filter
from trimesh.voxel.ops import matrix_to_marching_cubes

from model_generator.mesh_from_image import (
    _extract_foreground_mask,
    _mask_bbox_slices,
    _resize_gray_to_shape,
    _subsample_mask,
    _tight_bbox_crop,
)


def _bbox_crop_enabled() -> bool:
    return os.environ.get("MODEL_GENERATOR_NO_BBOX_CROP", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    )


def _top_bottom_erode_enabled() -> bool:
    return os.environ.get("MODEL_GENERATOR_TOP_BOTTOM_ERODE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _voxel_open_enabled() -> bool:
    return os.environ.get("MODEL_GENERATOR_VOXEL_OPEN", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _auto_plan_orient_enabled() -> bool:
    """Try original vs transposed top/bottom unless ``MODEL_GENERATOR_NO_AUTO_PLAN_SWAP=1``."""
    return os.environ.get("MODEL_GENERATOR_NO_AUTO_PLAN_SWAP", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    )


def _resize_side_to_match_front_height(
    side_img: Image.Image,
    target_height: int,
) -> Image.Image:
    w, h = side_img.size
    if h == target_height:
        return side_img
    ratio = target_height / h
    new_w = max(4, int(round(w * ratio)))
    return side_img.resize((new_w, target_height), Image.Resampling.LANCZOS)


def _resize_mask_nearest(mask: NDArray[np.bool_], new_h: int, new_w: int) -> NDArray[np.bool_]:
    im = Image.fromarray(mask.astype(np.uint8) * 255, mode="L")
    im = im.resize((new_w, new_h), Image.Resampling.NEAREST)
    return np.array(im) > 128


def _voxel_pitch_xyz(wf: int, hf: int, ws: int, denom: int, plane_scale: float) -> NDArray[np.float64]:
    """
    Physical spacing per voxel so **world proportions** match mask pixel counts.

    Without this, a long body (large **side** width ``ws`` vs **front** width ``wf``) is
    squashed when the mesh is scaled uniformly — the **top** view then cannot match the
    perceived length from art.
    """
    mx = max(float(wf), float(hf), float(ws), 1.0)
    return (
        np.array([float(wf), float(hf), float(ws)], dtype=np.float64)
        / mx
        * float(plane_scale)
        / float(max(denom, 1))
    )


def _top_bottom_mask_candidates(tm: NDArray[np.bool_], ws: int, wf: int) -> list[NDArray[np.bool_]]:
    """Original and transposed resize — many assets have length along the wrong image axis."""
    a = _resize_mask_nearest(tm, ws, wf)
    b = _resize_mask_nearest(tm.T, ws, wf)
    if a.shape == b.shape and np.array_equal(a, b):
        return [a]
    return [a, b]


def _pick_best_plan_mask(
    candidates: list[NDArray[np.bool_]],
    fs_inside: NDArray[np.bool_],
    side_iz: NDArray[np.intp],
    front_ix: NDArray[np.intp],
) -> NDArray[np.bool_]:
    """
    Prefer the orientation that **actually constrains** the hull (removes voxels) while
    keeping enough volume.
    """
    base_cnt = int(fs_inside.sum())
    if base_cnt < 8:
        return candidates[0]
    min_keep = max(8, base_cnt // 25)

    best = candidates[0]
    best_removed = -1
    for cand in candidates:
        trial = fs_inside & cand[side_iz, front_ix]
        tsum = int(trial.sum())
        if tsum < min_keep:
            continue
        removed = base_cnt - tsum
        if removed > best_removed:
            best_removed = removed
            best = cand

    if best_removed >= 0:
        return best

    for cand in candidates:
        trial = fs_inside & cand[side_iz, front_ix]
        if int(trial.sum()) >= 8:
            return cand
    return candidates[0]


def _silhouette_row_gate(mask: NDArray[np.bool_]) -> NDArray[np.float64]:
    """
    Per-row weight ``(H, 1)``: **1** near the **top** of the tight silhouette (head), fading
    toward the **belly/legs**.  Stops fur **spots** on the body from being treated as eyes and
    stops **luminance carve** from trenching the whole torso.
    """
    h = int(mask.shape[0])
    rows = np.any(mask, axis=1)
    if not np.any(rows):
        return np.ones((h, 1), dtype=np.float64)
    ry = np.where(rows)[0]
    r0, r1 = int(ry[0]), int(ry[-1])
    span = max(r1 - r0 + 1, 1)
    idx = np.arange(h, dtype=np.float64)
    y_norm = (idx - float(r0)) / float(span)
    # Strong in upper ~45% of creature; fade out by ~62% (mouth/cheek still in; spots on belly out).
    gate = np.clip(1.0 - (y_norm - 0.45) / 0.12, 0.0, 1.0)
    return gate[:, np.newaxis]


def _detect_front_features(
    gray: NDArray[np.float64],
    mask: NDArray[np.bool_],
) -> NDArray[np.float64]:
    """
    Detect **dark feature blobs** (eyes, mouth, nostrils) as regions significantly darker
    than their local surroundings within the foreground. Returns a ``[0, 1]`` recess map.
    """
    if not np.any(mask):
        return np.zeros_like(gray)
    h, w = gray.shape
    sigma = max(2.0, min(h, w) / 10.0)

    g_masked = gray * mask.astype(np.float64)
    blurred = gaussian_filter(g_masked, sigma=sigma)
    norm = np.maximum(gaussian_filter(mask.astype(np.float64), sigma=sigma), 1e-8)
    local_mean = blurred / norm

    darkness = np.clip((local_mean - gray) * mask, 0.0, 1.0)
    dmax = float(darkness.max())
    if dmax < 0.02:
        return np.zeros_like(gray)
    darkness /= dmax

    features = np.where(darkness > 0.25, darkness, 0.0)
    features = gaussian_filter(features, sigma=max(1.0, sigma * 0.25))
    fmax = float(features.max())
    if fmax > 0:
        features /= fmax
    return features


def _sculpt_hull_field(
    inside: NDArray[np.bool_],
    front_mask: NDArray[np.bool_],
    side_mask: NDArray[np.bool_],
    gray_fw: NDArray[np.float64],
    front_iy: NDArray[np.intp],
    front_ix: NDArray[np.intp],
    side_iy: NDArray[np.intp],
    side_iz: NDArray[np.intp],
    ii: NDArray[np.float64],
    jj: NDArray[np.float64],
    kk: NDArray[np.float64],
    r: int,
    rounding: float,
    gray_depth: float,
) -> NDArray[np.float64]:
    """
    Build a **soft scalar field** from the boolean hull for marching cubes at 0.5.

    Three complementary passes:

    1. **Rounding** — front + side distance transforms restrict depth/width near silhouette
       edges so the nape and sides curve instead of staying flat.
    2. **Feature recesses** — dark blobs (eyes, mouth) in the front image get a small
       inward dent near the front surface so marching cubes reads them as geometry.
    3. **Luminance depth** — global bright/dark shading shifts depth (existing behaviour).
    """
    denom = max(r - 1, 1)
    field = inside.astype(np.float64)

    # --- 1. Hull rounding via distance transforms ---
    if rounding > 1e-6:
        front_dist = distance_transform_edt(front_mask).astype(np.float64)
        fd_max = float(front_dist.max())
        if fd_max > 0:
            front_dist /= fd_max

        side_dist = distance_transform_edt(side_mask).astype(np.float64)
        sd_max = float(side_dist.max())
        if sd_max > 0:
            side_dist /= sd_max

        fd = front_dist[front_iy, front_ix]
        sd = side_dist[side_iy, side_iz]

        k_centered = np.abs(2.0 * kk / denom - 1.0)
        i_centered = np.abs(2.0 * ii / denom - 1.0)

        # Depth tapering — rounds front face and nape
        z_excess = np.clip(k_centered * rounding - fd, 0.0, None)
        z_factor = np.clip(1.0 - z_excess / 0.18, 0.0, 1.0)
        # Width tapering — rounds left/right sides
        x_excess = np.clip(i_centered * rounding - sd, 0.0, None)
        x_factor = np.clip(1.0 - x_excess / 0.18, 0.0, 1.0)

        field *= z_factor * x_factor

    row_gate = _silhouette_row_gate(front_mask)

    # --- 2. Feature recesses (eyes, mouth) — only in **head** rows (not body spots) ---
    feat_strength = max(rounding, gray_depth)
    if feat_strength > 0.04:
        feature_map = _detect_front_features(gray_fw, front_mask) * row_gate
        if float(feature_map.max()) > 0.01:
            feat = feature_map[front_iy, front_ix]

            k_idx = np.broadcast_to(np.arange(r)[np.newaxis, np.newaxis, :], (r, r, r))
            hull_k = np.where(inside, k_idx, r)
            min_k = hull_k.min(axis=2)[:, :, np.newaxis]

            front_depth = (k_idx - min_k).astype(np.float64)
            surface_zone = np.clip(1.0 - front_depth / 4.0, 0.0, 1.0)

            recess = feat * surface_zone * feat_strength * 0.45
            field -= recess
            field = np.clip(field, 0.0, 1.0)

    # --- 3. Luminance depth (bright = forward, dark = recessed) ---
    if gray_depth > 1e-6:
        g = np.clip(gray_fw[front_iy, front_ix], 0.0, 1.0)
        z_n = kk / denom
        head_w = row_gate[front_iy, 0]

        dark = np.clip((0.5 - g) * 2.0, 0.0, 1.0)
        carve = np.clip(gray_depth * 0.92 * dark * (1.0 - z_n) * head_w, 0.0, 0.48)
        field *= 1.0 - carve

        bright = np.clip((g - 0.5) * 2.0, 0.0, 1.0)
        field += bright * gray_depth * 0.38 * (1.0 - z_n) * inside.astype(np.float64)
        field = np.clip(field, 0.0, 1.0)

    if not np.any(field > 0.5):
        return inside.astype(np.float64)
    return field


def mesh_from_front_side(
    front_image: Image.Image,
    side_image: Image.Image,
    *,
    top_image: Image.Image | None = None,
    back_image: Image.Image | None = None,
    bottom_image: Image.Image | None = None,
    voxel_resolution: int = 64,
    plane_scale: float = 1.0,
    mirror_side: bool = False,
    hull_gray_depth: float = 0.0,
    hull_rounding: float = 0.35,
) -> trimesh.Trimesh:
    """
    Visual hull from **front** + **side**; optional **top**, **back**, **bottom** tighten
    the volume.

    ``hull_rounding`` (0.3--0.6) tapers depth/width near silhouette edges, rounds the
    nape and sides, and auto-recesses dark feature blobs on the front surface.

    ``hull_gray_depth`` (0.12--0.28) adds luminance depth.
    """
    front = front_image.convert("RGBA") if front_image.mode == "RGBA" else front_image.convert("RGB")
    side = side_image.convert("RGBA") if side_image.mode == "RGBA" else side_image.convert("RGB")

    # Match canvas height **before** masks so rows ≈ same world Y (ortho convention).
    side = _resize_side_to_match_front_height(side, front.size[1])

    front_mask_full = _extract_foreground_mask(front)
    gray_front = np.asarray(front.convert("L"), dtype=np.float64) / 255.0
    if gray_front.shape[:2] != front_mask_full.shape:
        gray_front = _resize_gray_to_shape(gray_front, front_mask_full.shape)

    side_mask_full = _extract_foreground_mask(side)

    if _bbox_crop_enabled():
        sl = _mask_bbox_slices(front_mask_full)
        if sl is not None:
            sy, sx = sl
            front_mask_full = front_mask_full[sy, sx]
            gray_front = gray_front[sy, sx]
        side_mask_full = _tight_bbox_crop(side_mask_full)

    front_mask = _subsample_mask(front_mask_full, max(voxel_resolution, 32))
    gray_fw = _resize_gray_to_shape(gray_front, front_mask.shape)
    side_mask = _subsample_mask(side_mask_full, max(voxel_resolution, 32))

    if front_mask.shape[0] != side_mask.shape[0]:
        sh = side_mask.shape[0]
        target_h = front_mask.shape[0]
        side_im = Image.fromarray(side_mask.astype(np.uint8) * 255, mode="L")
        side_im = side_im.resize((side_mask.shape[1], target_h), Image.Resampling.NEAREST)
        side_mask = np.array(side_im) > 128

    hf, wf = front_mask.shape
    hs, ws = side_mask.shape

    if hf < 4 or wf < 4 or hs < 4 or ws < 4:
        raise ValueError("Silhouette masks are too small after preprocessing.")

    top_tm_sub: NDArray[np.bool_] | None = None
    if top_image is not None:
        tim = top_image.convert("RGBA") if top_image.mode == "RGBA" else top_image.convert("RGB")
        tm = _extract_foreground_mask(tim)
        if _bbox_crop_enabled():
            tm = _tight_bbox_crop(tm)
        top_tm_sub = _subsample_mask(tm, max(voxel_resolution, 32))

    bottom_bm_sub: NDArray[np.bool_] | None = None
    if bottom_image is not None:
        bim = bottom_image.convert("RGBA") if bottom_image.mode == "RGBA" else bottom_image.convert("RGB")
        bm = _extract_foreground_mask(bim)
        if _bbox_crop_enabled():
            bm = _tight_bbox_crop(bm)
        bottom_bm_sub = _subsample_mask(bm, max(voxel_resolution, 32))

    back_mask: NDArray[np.bool_] | None = None
    if back_image is not None:
        bim = back_image.convert("RGBA") if back_image.mode == "RGBA" else back_image.convert("RGB")
        bm = _extract_foreground_mask(bim)
        if _bbox_crop_enabled():
            bm = _tight_bbox_crop(bm)
        bm = _subsample_mask(bm, max(voxel_resolution, 32))
        back_mask = _resize_mask_nearest(bm, hf, wf)

    r = max(8, min(int(voxel_resolution), 128))

    ii, jj, kk = np.indices((r, r, r), dtype=np.float64)
    denom = max(r - 1, 1)
    pitch = _voxel_pitch_xyz(wf, hf, ws, denom, float(plane_scale))

    front_ix = np.clip(np.round(ii / denom * (wf - 1)).astype(np.intp), 0, wf - 1)
    front_iy = np.clip(np.round(jj / denom * (hf - 1)).astype(np.intp), 0, hf - 1)
    side_iy = np.clip(np.round(jj / denom * (hs - 1)).astype(np.intp), 0, hs - 1)
    side_iz = np.clip(np.round(kk / denom * (ws - 1)).astype(np.intp), 0, ws - 1)

    side_ok = side_mask[side_iy, side_iz]
    if mirror_side and ws > 1:
        side_ok = side_ok & side_mask[side_iy, ws - 1 - side_iz]

    fs_inside = front_mask[front_iy, front_ix] & side_ok

    top_mask: NDArray[np.bool_] | None = None
    if top_tm_sub is not None:
        if _auto_plan_orient_enabled():
            cands = _top_bottom_mask_candidates(top_tm_sub, ws, wf)
            top_mask = _pick_best_plan_mask(cands, fs_inside, side_iz, front_ix)
        else:
            top_mask = _resize_mask_nearest(top_tm_sub, ws, wf)
        if _top_bottom_erode_enabled():
            top_mask = binary_erosion(top_mask, iterations=1)

    inside = fs_inside
    if top_mask is not None:
        inside = inside & top_mask[side_iz, front_ix]

    bottom_mask: NDArray[np.bool_] | None = None
    if bottom_bm_sub is not None:
        if _auto_plan_orient_enabled():
            cands = _top_bottom_mask_candidates(bottom_bm_sub, ws, wf)
            bottom_mask = _pick_best_plan_mask(cands, inside, side_iz, front_ix)
        else:
            bottom_mask = _resize_mask_nearest(bottom_bm_sub, ws, wf)
        if _top_bottom_erode_enabled():
            bottom_mask = binary_erosion(bottom_mask, iterations=1)
        inside = inside & bottom_mask[side_iz, front_ix]

    if back_mask is not None:
        back_iy = front_iy
        back_ix = wf - 1 - front_ix
        inside = inside & back_mask[back_iy, back_ix]

    # Optional: break thin voxel bridges (can also flatten depth — off by default).
    if _voxel_open_enabled() and (
        top_mask is not None or bottom_mask is not None or back_mask is not None
    ):
        struct = np.ones((2, 2, 2), dtype=bool)
        opened = binary_opening(inside, structure=struct)
        if opened.sum() >= 8:
            inside = opened

    if inside.sum() < 8:
        raise ValueError(
            "Silhouettes do not overlap enough in 3D. Match framing (same height), clear backgrounds, "
            "or disable extra views / mirror_side."
        )

    needs_sculpt = hull_rounding > 1e-6 or hull_gray_depth > 1e-6
    if needs_sculpt:
        scalar = _sculpt_hull_field(
            inside,
            front_mask,
            side_mask,
            gray_fw,
            front_iy,
            front_ix,
            side_iy,
            side_iz,
            ii,
            jj,
            kk,
            r,
            rounding=float(hull_rounding),
            gray_depth=float(hull_gray_depth),
        )
        mesh = matrix_to_marching_cubes(scalar, pitch=pitch, threshold=0.5)
    else:
        mesh = matrix_to_marching_cubes(inside.astype(np.float64), pitch=pitch)
    ext = float(mesh.extents.max())
    if ext < 1e-8:
        raise ValueError("Degenerate visual hull.")
    mesh.apply_scale(float(plane_scale) / ext)
    mesh.apply_translation(-mesh.centroid)
    mesh.process()
    mesh.fix_normals()
    return mesh
