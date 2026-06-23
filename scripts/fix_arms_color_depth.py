"""
fix_arms_color_depth.py — Colour-guided arm depth separation.

For a 3D mesh where upper-body limbs are merged/flat because they were
generated from a single image with no depth cue, this script uses the
original reference image to separate them physically:

  1.  Load the mesh (GLB/FBX/OBJ) and the reference image.
  2.  Isolate the arm region by Z height (configurable fraction of total height).
  3.  Project each arm vertex orthographically onto the reference image using a
      configurable 3/4-view camera angle (Blender Z-up, Y-forward convention).
  4.  Sample the image colour at each projected pixel.
  5.  Cluster arm vertices into TWO groups by luminance:
        bright = front arm  (closer to camera in the reference image)
        dark   = back arm   (farther from camera)
  6.  Push the bright group forward (−Y) and the dark group backward (+Y),
      separating the merged limbs along the depth axis.
  7.  Export the repaired mesh.

Coordinate convention (Blender / autorig output):
  X = left/right   Y = forward/backward (depth)   Z = up/down (height)

Usage
-----
python fix_arms_color_depth.py input.glb reference.png output.glb [options]

Options
-------
  --az   DEG   Camera azimuth from −Y front axis toward −X (left) in degrees.
               Default 45 (camera to the front-left of the creature).
  --el   DEG   Camera elevation above horizontal in degrees. Default 15.
  --arm-low  F  Lower Z-fraction of arm region (default 0.45).
  --arm-high F  Upper Z-fraction of arm region (default 0.92).
  --depth-frac F  Depth push as fraction of mesh Y range (default 0.18).
  --min-sep F   Skip if two clusters are already separated by this fraction of
               Y range — mesh probably fine (default 0.05).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _load_mesh(path: str):
    import trimesh
    m = trimesh.load(path, force="mesh", process=False)
    return m


def _camera_axes(az_deg: float, el_deg: float):
    """Return (right, up) unit vectors for orthographic projection.

    Convention: Blender Z-up, Y-forward.  Azimuth rotates from the -Y front
    axis toward the -X axis (camera to the front-left of the creature).
    Elevation tilts the camera upward.

    Returns
    -------
    right : (3,) ndarray  — image +U direction in world space
    up    : (3,) ndarray  — image +V direction in world space (world up = Z)
    """
    az = np.radians(az_deg)
    el = np.radians(el_deg)

    # Camera position direction from origin (azimuth in XY plane around Z):
    # start at -Y (front), rotate toward -X.
    cam_x = -np.sin(az)             # negative = left side of creature
    cam_y = -np.cos(az)             # negative = front side
    cam_z = np.sin(el)
    cam_dir = np.array([cam_x, cam_y, cam_z])
    cam_dir /= np.linalg.norm(cam_dir)

    # View direction: from camera toward origin
    view = -cam_dir

    # Right = cross(view, world_up); normalise
    world_up = np.array([0.0, 0.0, 1.0])
    right = np.cross(view, world_up)
    norm = np.linalg.norm(right)
    if norm < 1e-9:
        right = np.array([1.0, 0.0, 0.0])
    else:
        right /= norm

    # Up = world Z projected onto the camera plane (reject the view component)
    up = world_up - np.dot(world_up, view) * view
    norm = np.linalg.norm(up)
    if norm < 1e-9:
        up = np.array([0.0, 0.0, 1.0])
    else:
        up /= norm

    return right, up


def _project_vertices(verts: np.ndarray, right: np.ndarray, up: np.ndarray,
                      ref_verts: np.ndarray | None = None):
    """Orthographic project *verts* to (u, v) in [0, 1].

    *ref_verts* is used for the global bounding box (so arm verts don't
    get normalised to their own tight range, which would distort the image
    lookup).
    """
    if ref_verts is None:
        ref_verts = verts

    u_raw = ref_verts @ right
    v_raw = ref_verts @ up
    u_min, u_max = u_raw.min(), u_raw.max()
    v_min, v_max = v_raw.min(), v_raw.max()
    u_range = u_max - u_min or 1.0
    v_range = v_max - v_min or 1.0

    u = (verts @ right - u_min) / u_range
    v = 1.0 - (verts @ up - v_min) / v_range   # flip: image top = high Z

    return np.clip(u, 0.0, 1.0), np.clip(v, 0.0, 1.0)


def _sample_image(img_rgba: np.ndarray, u: np.ndarray, v: np.ndarray):
    """Nearest-pixel sample of *img_rgba* at normalised (u, v) coords."""
    H, W = img_rgba.shape[:2]
    px = np.clip((u * (W - 1)).astype(int), 0, W - 1)
    py = np.clip((v * (H - 1)).astype(int), 0, H - 1)
    return img_rgba[py, px]   # shape (N, 4) RGBA uint8


def _luminance(rgb: np.ndarray) -> np.ndarray:
    """Perceptual luminance from uint8 RGB columns."""
    return (0.299 * rgb[:, 0].astype(float)
            + 0.587 * rgb[:, 1].astype(float)
            + 0.114 * rgb[:, 2].astype(float))


# ---------------------------------------------------------------------------
# Main fix logic
# ---------------------------------------------------------------------------

def fix_arms_color_depth(
    input_path: str,
    ref_image_path: str,
    output_path: str,
    *,
    az_deg: float = 45.0,
    el_deg: float = 15.0,
    arm_low: float = 0.45,
    arm_high: float = 0.92,
    depth_frac: float = 0.18,
    min_sep_frac: float = 0.05,
) -> str:
    """Apply colour-guided depth separation and save result.  Returns a status string."""
    mesh = _load_mesh(input_path)
    verts = np.array(mesh.vertices, dtype=float)  # (N, 3)

    z_min, z_max = verts[:, 2].min(), verts[:, 2].max()
    z_range = z_max - z_min
    if z_range < 1e-6:
        return "Mesh Z range is near zero — aborting."

    y_min, y_max = verts[:, 1].min(), verts[:, 1].max()
    y_range = y_max - y_min

    # -- Arm region mask (by Z height) ---------------------------------------
    z_lo = z_min + z_range * arm_low
    z_hi = z_min + z_range * arm_high
    arm_mask = (verts[:, 2] >= z_lo) & (verts[:, 2] <= z_hi)
    n_arm = arm_mask.sum()

    print(f"[color_depth] Mesh: {len(verts)} verts, Z=[{z_min:.3f},{z_max:.3f}],"
          f" Y=[{y_min:.3f},{y_max:.3f}]")
    print(f"[color_depth] Arm region Z=[{z_lo:.3f},{z_hi:.3f}]: {n_arm} vertices"
          f" ({100*n_arm/len(verts):.1f}%)")

    if n_arm < 20:
        return f"Too few arm-region vertices ({n_arm}) — try adjusting --arm-low/--arm-high."

    # -- Load reference image with white-background removal ------------------
    img_arr = np.array(Image.open(ref_image_path).convert("RGBA"))
    r_ch = img_arr[:, :, 0].astype(int)
    g_ch = img_arr[:, :, 1].astype(int)
    b_ch = img_arr[:, :, 2].astype(int)
    # Mask near-white and near-neutral-gray (background) as transparent
    white_mask = (r_ch >= 230) & (g_ch >= 230) & (b_ch >= 230)
    img_arr[white_mask, 3] = 0
    img = img_arr
    opaque_px_count = int((img[:, :, 3] > 20).sum())
    print(f"[color_depth] Reference image: {img.shape[1]}×{img.shape[0]} px,"
          f" {opaque_px_count} non-background pixels")

    # -- Project arm vertices onto the image ---------------------------------
    right, up = _camera_axes(az_deg, el_deg)
    print(f"[color_depth] Camera: az={az_deg}° el={el_deg}°  right={right}  up={up}")

    arm_verts = verts[arm_mask]
    u, v = _project_vertices(arm_verts, right, up, ref_verts=verts)

    sampled = _sample_image(img, u, v)   # (n_arm, 4) RGBA
    alpha = sampled[:, 3].astype(float)
    rgb   = sampled[:, :3]

    # Filter to pixels that actually hit the creature (non-background alpha > 20)
    opaque = alpha > 20
    print(f"[color_depth] Arm verts hitting creature pixels: "
          f"{opaque.sum()} / {n_arm} ({100*opaque.sum()/n_arm:.1f}%)")

    if opaque.sum() < 20:
        print("[color_depth] WARNING: few creature hits — projection may be misaligned."
              "  Try --az / --el adjustments.  Proceeding with all arm verts.")
        opaque = np.ones(n_arm, dtype=bool)

    # -- Spatial K-means: find two arm clusters by 3D position -----------------
    # Using X and Y coordinates only (ignore Z height within the arm zone).
    # This finds the two laterally/depth-separated foreleg clusters without
    # being confused by colour differences between body and claw tips.
    try:
        from sklearn.cluster import KMeans
        _kmeans_ok = True
    except ImportError:
        _kmeans_ok = False

    if _kmeans_ok:
        coords_2d = arm_verts[:, :2]   # X, Y — the two coordinates that separate arms
        km = KMeans(n_clusters=2, n_init=10, random_state=42)
        labels = km.fit_predict(coords_2d)
        cluster_a_local = labels == 0
        cluster_b_local = labels == 1
    else:
        # Fallback: split by median Y within arm zone (no sklearn needed)
        y_mid = float(np.median(arm_verts[:, 1]))
        cluster_a_local = arm_verts[:, 1] <= y_mid
        cluster_b_local = ~cluster_a_local

    cluster_a_idx = np.where(arm_mask)[0][cluster_a_local]
    cluster_b_idx = np.where(arm_mask)[0][cluster_b_local]

    print(f"[color_depth] Spatial clusters: A={len(cluster_a_idx)}, B={len(cluster_b_idx)}")

    if len(cluster_a_idx) < 5 or len(cluster_b_idx) < 5:
        return "Spatial clustering produced a near-empty group."

    # -- Use image luminance to determine which cluster faces the camera -------
    # Project each cluster's centroid to the image and compare luminance.
    # The BRIGHTER cluster faces the camera more directly -> it is the front arm.
    def _cluster_lum(cidx: np.ndarray) -> float:
        cv = verts[cidx]
        u_c, v_c = _project_vertices(cv, right, up, ref_verts=verts)
        samp = _sample_image(img, u_c, v_c)
        a = samp[:, 3].astype(float)
        opq = a > 20
        if opq.sum() < 5:
            return 0.0
        return float(_luminance(samp[:, :3])[opq].mean())

    lum_a = _cluster_lum(cluster_a_idx)
    lum_b = _cluster_lum(cluster_b_idx)
    print(f"[color_depth] Cluster A mean lum={lum_a:.1f},  B mean lum={lum_b:.1f}")

    # Brighter = front (faces camera); darker = back
    if lum_a >= lum_b:
        front_indices, back_indices = cluster_a_idx, cluster_b_idx
        print("[color_depth] Cluster A -> front arm,  Cluster B -> back arm")
    else:
        front_indices, back_indices = cluster_b_idx, cluster_a_idx
        print("[color_depth] Cluster B -> front arm,  Cluster A -> back arm")

    # -- Check if already separated enough -----------------------------------
    y_front = verts[front_indices, 1]
    y_back  = verts[back_indices,  1]
    existing_sep = y_back.mean() - y_front.mean()   # positive = back is behind front (correct)
    print(f"[color_depth] Y separation (back_mean - front_mean): {existing_sep:.4f}"
          f"  (min_sep threshold: {min_sep_frac * y_range:.4f})")

    if min_sep_frac > 0 and existing_sep > min_sep_frac * y_range:
        return (f"Arms appear already separated (Y gap {existing_sep:.4f} >"
                f" {min_sep_frac * y_range:.4f}).  No change applied.")

    # -- Apply depth push: shift each cluster by half the desired separation ---
    # Target separation = depth_frac * y_range.
    # We move front arm forward (−Y) and back arm backward (+Y) symmetrically.
    # Clamp per-vertex push so no vertex moves more than 2× y_range from its original pos.
    push = depth_frac * y_range
    print(f"[color_depth] Pushing front arm by -{push:.4f} Y,"
          f"  back arm by +{push:.4f} Y  (depth_frac={depth_frac})")

    new_verts = verts.copy()
    new_verts[front_indices, 1] -= push
    new_verts[back_indices,  1] += push

    mesh.vertices = new_verts

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(str(out))

    return (f"Done.  Front arm ({len(front_indices)} verts) pushed -Y by {push:.4f},"
            f"  back arm ({len(back_indices)} verts) pushed +Y by {push:.4f}."
            f"  Saved -> {out}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse():
    p = argparse.ArgumentParser(
        description="Colour-guided arm depth separation for merged-arm meshes.")
    p.add_argument("input_glb",    help="Input GLB/FBX/OBJ mesh.")
    p.add_argument("reference_img", help="Reference image used during generation.")
    p.add_argument("output_glb",   help="Output GLB path.")
    p.add_argument("--az",   type=float, default=45.0,
                   help="Camera azimuth degrees from front toward left (default 45).")
    p.add_argument("--el",   type=float, default=15.0,
                   help="Camera elevation degrees (default 15).")
    p.add_argument("--arm-low",  type=float, default=0.45,
                   help="Lower Z-fraction of arm region (default 0.45).")
    p.add_argument("--arm-high", type=float, default=0.92,
                   help="Upper Z-fraction of arm region (default 0.92).")
    p.add_argument("--depth-frac", type=float, default=0.18,
                   help="Depth push as fraction of mesh Y range (default 0.18).")
    p.add_argument("--min-sep", type=float, default=0.05,
                   help="Skip if arms already separated by this Y fraction (default 0.05).")
    return p.parse_args()


def main():
    args = _parse()
    result = fix_arms_color_depth(
        args.input_glb,
        args.reference_img,
        args.output_glb,
        az_deg=args.az,
        el_deg=args.el,
        arm_low=args.arm_low,
        arm_high=args.arm_high,
        depth_frac=args.depth_frac,
        min_sep_frac=args.min_sep,
    )
    print(f"[color_depth] {result}")


if __name__ == "__main__":
    main()
