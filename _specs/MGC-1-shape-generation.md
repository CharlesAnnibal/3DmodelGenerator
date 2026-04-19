---
status: done
---

# MGC-1 — 3D Model Shape Generation

## Problem
The pipeline needs to convert 2D reference images into a 3D triangular mesh. This is the core generation step that all downstream processing (texturing, rigging) depends on.

## Goal
Take one or more creature reference images and produce a raw 3D mesh via the Hunyuan3D-2 diffusion model, with support for both single-view and multi-view input.

## Scope

### In scope
- Single-view and multi-view model selection
- Mirrored-view deduplication
- Front+back rejection (prevents extra limb artifacts)
- CUDA/CPU auto-detection
- Pipeline weight caching across batch creatures
- CLI flags for steps, octree resolution, chunks, seed, preset

### Out of scope
- Texture baking (MGC-2)
- Rigging (MGC-3)
- Scale normalization (MGC-4)

## Current state
Documents the shape generation pipeline as it is implemented today.

---

## 1. Input Discovery

The CLI scans each creature subfolder under `--input-dir` (default `./input`) and maps
standard view names to image files.

Recognised view names (checked in this order): `front`, `back`, `side`, `left`, `right`  
Recognised extensions: `.png`, `.jpg`, `.jpeg`, `.webp`

One file per view name is loaded. If both `side` and `left/right` are present, `side`
is aliased to `left` internally.

After a successful run the source images are renamed with a `_processed` suffix to
prevent accidental re-runs.

---

## 2. Background Removal

Run by default; skipped with `--no-rembg`.

Each loaded image is passed through **rembg** (`maybe_rembg`), which removes the
background and returns an RGBA image. The alpha channel is preserved and used later
in texture blending.

---

## 3. Mirrored-View Deduplication

Before shape generation, `deduplicate_mirrored_views` compares left/right views
pixel-by-pixel. If they are near-identical (horizontally mirrored) one is dropped to
avoid feeding the model redundant information that can confuse limb placement.
Warnings are emitted for any dropped view.

---

## 4. Shape Generation — Model Selection

### Multi-view path (≥ 2 views)

Model: `tencent/Hunyuan3D-2mv` / subfolder `hunyuan3d-dit-v2-mv`

The pipeline image dict is passed directly. Required combinations:
- `front` + at least one of `left` / `right` ← minimum valid multi-view set
- `front` + `back` alone is **rejected** (raises `RuntimeError`) because the model
  tends to invent extra limbs when given only front + back with no depth cue.

### Single-view path (1 view)

Three presets selectable via `--preset`:

| Preset                          | Repo                     | Subfolder                        |
|---------------------------------|--------------------------|----------------------------------|
| `Hunyuan3D-2 (quality)`         | `tencent/Hunyuan3D-2`    | `hunyuan3d-dit-v2-0`             |
| `Hunyuan3D-2 Turbo (faster)`    | `tencent/Hunyuan3D-2`    | `hunyuan3d-dit-v2-0-turbo`       |
| `Hunyuan3D-2mini (low VRAM)`    | `tencent/Hunyuan3D-2mini`| `hunyuan3d-dit-v2-mini`          |

Default preset: `Hunyuan3D-2 (quality)`.

### Inference parameters (CLI flags)

| Parameter           | Flag                  | CLI default | Preset default |
|---------------------|-----------------------|-------------|----------------|
| Diffusion steps     | `--steps`             | 40          | 20 / 10 / 15   |
| Octree resolution   | `--octree-resolution` | 260         | 128            |
| Chunk count         | `--num-chunks`        | 20 000      | 8 000          |
| Seed                | `--seed`              | 12 345      | —              |

> **Note:** CLI defaults override preset defaults. The preset values above only apply if
> `--preset` is set and none of the individual flags are passed explicitly.

### Hardware
- CUDA available → `fp16` on GPU
- No CUDA → `fp32` on CPU

Pipeline weights are cached in `_shape_cache` (keyed by model path + subfolder +
device + dtype) so they survive across creatures in a batch run without reloading.

---

## 5. Raw Mesh Export

The trimesh object returned by the pipeline is exported to a temporary GLB file.
This is `current_glb` — the working file that subsequent steps consume and replace.

---

## 6. Leg-Fix (`fix_merged_legs_blender.py`)

Run by default; skipped with `--no-fix-legs`.

Invoked headlessly via Blender. The script:

1. Imports the GLB and joins all mesh objects into one.
2. Scans the lower 38 % of the mesh height for vertex clusters (leg columns).
   Merge distance = 18 % of max(width, depth).
3. For each cluster, computes `depth_Y / width_X`. If ratio < 0.35 the leg is
   considered **flat** (AI generated no depth because the reference image gave no cue).
4. Fixes flat legs:
   - **Quadruped / auto (≥ 2 flat clusters):** splits each cluster into front-half and
     back-half, offsets them ±Y to create depth separation.
   - **Humanoid / single flat cluster:** thickens the leg by pushing vertices outward
     along Y symmetrically.
5. Exports the fixed GLB.

If the Blender call fails, `current_glb` stays unchanged and a warning is emitted.

---

## 7. Output Files

After shape generation (before texturing and rigging):

```
output/{name}/3dmodel/
  {name}.glb              ← untextured auto-rigged model (written in step 6 of pipeline)
```

The raw and leg-fixed GLBs are temporary files, cleaned up after the pipeline completes.
