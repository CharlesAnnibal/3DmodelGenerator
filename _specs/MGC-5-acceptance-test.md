---
status: done
---

# MGC-5 — Acceptance Test Suite

## Problem
The pipeline can fail silently: textures bake all-black, rigs have zero-weight vertices, meshes are degenerate or inverted. Without automated checks, every creature requires manual visual inspection.

## Goal
Run an automated quality gate at the end of each creature generation that validates file integrity, mesh quality, texture quality, rigging integrity, and visual correctness via renders compared against reference images.

## Scope

### In scope
- File existence and size checks (F-01 to F-06)
- Mesh quality checks via trimesh (M-01 to M-10)
- Texture quality checks via PIL (T-01 to T-05)
- Rigging checks via pygltflib (G-01 to G-05)
- Headless Blender EEVEE renders at 6 camera positions
- Render-based visual checks with histogram comparison (R-01 to R-08)
- Pass/fail scoring with severity weights
- `acceptance.json` output artifact
- CLI flags: `--no-acceptance`, `--strict`

### Out of scope
- ML-based quality scoring (CLIP similarity)
- Unity-side validation
- Perceptual diff against golden renders

## Current state
These are the assertions that must pass for a creature generation to be considered successful.
They are run automatically at the end of the pipeline by `acceptance.py`.

---

## 1. Output File Checks

| ID    | Check                                              | Pass condition                        | Severity |
|-------|----------------------------------------------------|---------------------------------------|----------|
| F-01  | `{name}_textured_rigged.glb` exists                | File present                          | CRITICAL |
| F-02  | `{name}_textured_rigged.glb` is not empty          | Size > 500 KB                         | CRITICAL |
| F-03  | `{name}_textured.glb` exists                       | File present                          | HIGH     |
| F-04  | `textures/{name}.png` (albedo) exists              | File present                          | HIGH     |
| F-05  | Albedo PNG is not empty                            | File size > 10 KB                     | HIGH     |
| F-06  | `_textured_rigged.glb` loads without error         | `trimesh.load()` succeeds             | CRITICAL |

---

## 2. Mesh Quality Checks

Loaded from `_textured_rigged.glb` via trimesh.

| ID    | Check                              | Pass condition                                | Severity |
|-------|------------------------------------|-----------------------------------------------|----------|
| M-01  | Vertex count in valid range        | 5 000 ≤ vertices ≤ 500 000                    | HIGH     |
| M-02  | Face count in valid range          | 3 000 ≤ faces ≤ 1 000 000                     | HIGH     |
| M-03  | No NaN or Inf in vertex positions  | `np.isfinite(vertices).all()`                 | CRITICAL |
| M-04  | Bounding box is not degenerate     | All 3 dimensions > 0.01 (world units)         | CRITICAL |
| M-05  | Reasonable aspect ratio            | height / max(width, depth) between 0.2 and 10 | MEDIUM   |
| M-06  | Connected component count          | 1 ≤ components ≤ 5                            | MEDIUM   |
| M-07  | No zero-area faces                 | All face areas > 1e-8                         | MEDIUM   |
| M-08  | Vertex normals present             | Normal array exists and is unit-length        | HIGH     |

---

## 2b. Scale / Size Checks

Convention: **1 unit = 1 metre** (glTF/GLB standard). The pipeline rescales every creature
to the requested target height before fix_legs and autorig.

### Size presets (CLI)

| Flag / value         | Target height | Tolerance band  |
|----------------------|--------------|-----------------|
| `--small` / `"small"` | 0.30 m       | 0.27 – 0.33 m   |
| `--medium` / `"medium"` (default) | 1.00 m | 0.90 – 1.10 m |
| `--big` / `"big"`    | 2.50 m       | 2.25 – 2.75 m   |
| `--huge` / `"huge"`  | 5.00 m       | 4.50 – 5.50 m   |
| `--height <decimal>` | _user value_ | ±10% of value   |

`--height` accepts a decimal metres value **or** one of the preset strings. Preset flags
(`--small`, `--medium`, `--big`, `--huge`) are shorthand for `--height <preset>`. If both
are supplied, `--height` takes precedence.

### Acceptance checks

Loaded from `_textured_rigged.glb` via trimesh. Height = Z-axis extent (Z is up in
Blender/trimesh; the pipeline normalises on load).

| ID    | Check                                  | Pass condition                             | Severity |
|-------|----------------------------------------|--------------------------------------------|----------|
| M-09  | Creature height within target band     | `abs(bbox_Z − target) / target ≤ 0.10`    | HIGH     |
| M-10  | No degenerate scale (not flat/needle)  | `bbox_Z / max(bbox_X, bbox_Y) ∈ [0.1, 20]`| MEDIUM   |

---

## 3. Texture / Albedo Checks

Loaded from `textures/{name}.png`.

| ID    | Check                                  | Pass condition                                   | Severity |
|-------|----------------------------------------|--------------------------------------------------|----------|
| T-01  | Albedo is not black                    | > 15% of pixels have any channel > 10/255        | CRITICAL |
| T-02  | Albedo is not neutral gray             | < 80% of pixels within ±15 of (180, 180, 180)   | HIGH     |
| T-03  | Color variance is sufficient           | Per-channel std-dev of non-background pixels > 8 | HIGH     |
| T-04  | No single hue dominates unrealistically | No hue bucket > 60% of non-background pixels    | MEDIUM   |
| T-05  | Texture is not inverted/transparent    | Alpha channel mean > 0.3 (if RGBA)               | MEDIUM   |

---

## 4. Render-Based Checks

Produced by `render_views_blender.py` for each of the 6 standard views.
Renders are saved to `output/{name}/renders/{view}.png` (256×256 RGBA).

| ID    | View         | Check                                             | Pass condition                          | Severity |
|-------|--------------|---------------------------------------------------|-----------------------------------------|----------|
| R-01  | front        | Mesh is visible (not hollow/inverted)             | > 20% non-transparent pixels            | CRITICAL |
| R-02  | front        | No large black silhouette region                  | Non-background pixels > 10% non-black  | HIGH     |
| R-03  | front        | Color histogram matches front reference image     | Cosine similarity > 0.65               | HIGH     |
| R-04  | back         | Mesh is visible from back                         | > 15% non-transparent pixels            | HIGH     |
| R-05  | back         | Color histogram matches back reference (if avail) | Cosine similarity > 0.60               | MEDIUM   |
| R-06  | left         | Mesh is visible from side                         | > 10% non-transparent pixels            | HIGH     |
| R-07  | top          | Limbs are separated (not flat slab)               | Bounding box of visible pixels W/H < 3 | MEDIUM   |
| R-08  | 3/4 front    | Overall render is not black                       | > 20% non-transparent, non-black pixels | HIGH     |

**How histogram comparison works (R-03, R-05):**
1. Render the model front view at 256×256.
2. Mask out transparent/background pixels from both render and reference.
3. Compute 32-bin RGB histogram on foreground pixels for each.
4. Normalize both histograms to unit vectors.
5. Cosine similarity ≥ threshold = PASS.

This catches: black texture (similarity ≈ 0), wrong color (similarity < 0.5), and
confirms a reasonable match without requiring pixel-perfect alignment.

---

## 5. Rigging Checks

Loaded from `_textured_rigged.glb`. Requires trimesh + pygltflib or direct JSON parsing.

| ID    | Check                              | Pass condition                              | Severity |
|-------|------------------------------------|---------------------------------------------|----------|
| G-01  | Armature / skeleton exists         | At least one skin node in GLB               | CRITICAL |
| G-02  | Bone count                         | ≥ 8 bones (minimum viable rig)              | HIGH     |
| G-03  | No vertex has zero total weight    | All vertex weight sums > 0                  | HIGH     |
| G-04  | Weight normalization               | Per-vertex weight sum ∈ [0.95, 1.05]        | MEDIUM   |
| G-05  | Root bone at reasonable position   | Root bone Y position within mesh bounds     | MEDIUM   |

---

## 6. Render Setup (for `render_views_blender.py`)

Camera configuration (orthographic, fits mesh bounding box):

```
View        Azimuth    Elevation    Distance multiplier
front       0°         0°           1.8× bbox diagonal
back        180°       0°           1.8×
left        90°        0°           1.8×
right       270°       0°           1.8×
top         0°         90°          1.8×
3/4 front   45°        30°          2.0×
```

- Camera type: orthographic, scale = bbox_max_dimension × 1.2
- Background: transparent (alpha = 0)
- Engine: EEVEE (fast, deterministic)
- Samples: 16
- Resolution: 256 × 256

---

## 7. Pass / Fail Summary

- **CRITICAL failures**: creature is considered failed; warn loudly; do not copy to arena.
- **HIGH failures**: warning logged; creature proceeds but is flagged for review.
- **MEDIUM failures**: info logged; no action required.

Overall PASS = zero CRITICAL failures AND ≤ 2 HIGH failures.

---

## 8. Output Artifact

`output/{name}/acceptance.json`:
```json
{
  "creature": "1-pupplynx",
  "passed": true,
  "score": 0.91,
  "checks": [
    { "id": "T-01", "name": "Albedo not black", "passed": true, "value": "42.3%", "threshold": ">15%" },
    ...
  ],
  "renders": {
    "front": "output/1-pupplynx/renders/front.png",
    "back":  "output/1-pupplynx/renders/back.png",
    ...
  }
}
```
