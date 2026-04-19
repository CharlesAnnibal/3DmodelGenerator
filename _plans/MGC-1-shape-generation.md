# Plan: MGC-1 — 3D Model Shape Generation

The shape generation step takes 2D reference images and produces a 3D
triangular mesh via the Hunyuan3D-2 diffusion model.

## Affected files

| File | Change |
|---|---|
| `src/model_generator_cli/pipeline.py` | `_get_shape_pipeline()`, shape gen in `process_creature()` steps 3-4 |
| `src/model_generator_cli/__main__.py` | `--preset`, `--steps`, `--octree-resolution`, `--num-chunks`, `--seed` flags |
| `modelGenerator/src/model_generator/image_utils.py` | `maybe_rembg()`, `deduplicate_mirrored_views()` |

## Implementation steps

- [x] Step 1 — Define `PRESETS_SINGLE` and `PRESET_MV` model path constants
- [x] Step 2 — Implement `_get_shape_pipeline()` with lazy weight caching
- [x] Step 3 — Implement multi-view path: mirrored-view dedup, front+back rejection, MV model call
- [x] Step 4 — Implement single-view path: preset selection, single-image model call
- [x] Step 5 — Export trimesh result to temp GLB (`current_glb`)
- [x] Step 6 — Add scale normalization step 4b (moved to MGC-4)
- [x] Step 7 — Add mesh decimation step 4c (trimesh first, Blender fallback)
- [x] Step 8 — Add leg-fix step 5 via Blender script

---

## Model Selection

| Condition | Model | Repo |
|-----------|-------|------|
| >= 2 views | Hunyuan3D-2mv | `tencent/Hunyuan3D-2mv` / `hunyuan3d-dit-v2-mv` |
| 1 view, Quality preset | Hunyuan3D-2 | `tencent/Hunyuan3D-2` / `hunyuan3d-dit-v2-0` |
| 1 view, Turbo preset | Hunyuan3D-2 Turbo | `tencent/Hunyuan3D-2` / `hunyuan3d-dit-v2-0-turbo` |
| 1 view, Mini preset | Hunyuan3D-2mini | `tencent/Hunyuan3D-2mini` / `hunyuan3d-dit-v2-mini` |

---

## Input Validation

Before shape generation:

1. **Mirrored-view deduplication** — compares left/right views
   pixel-by-pixel. If near-identical (horizontally mirrored), one is
   dropped to avoid confusing the model (can invent extra limbs).

2. **Front+back rejection** — front+back only is explicitly rejected
   (raises `RuntimeError`) because the model tends to invent extra limbs
   when given only front+back with no depth cue. Minimum viable
   multi-view set: front + left or right.

---

## Inference Parameters

| Parameter | CLI flag | CLI default | Notes |
|-----------|----------|-------------|-------|
| Diffusion steps | `--steps` | 40 | More steps = better quality, slower |
| Octree resolution | `--octree-resolution` | 260 | Mesh detail level |
| Chunk count | `--num-chunks` | 20000 | GPU memory management |
| Seed | `--seed` | 12345 | Reproducibility |

**CLI defaults override preset defaults.** The preset values (20/10/15
steps) only apply if the user selects a preset and doesn't pass `--steps`.

---

## Hardware Paths

| CUDA available | Precision | Device | Typical time |
|----------------|-----------|--------|-------------|
| Yes | fp16 | GPU | ~2 minutes |
| No | fp32 | CPU | ~4+ hours (40 steps) |

The pipeline auto-detects CUDA via `torch.cuda.is_available()`. There is
no explicit CPU check or warning — if CUDA isn't found, it silently falls
back to CPU.

**CPU performance:** At ~400s/step with 40 steps, diffusion alone takes
~4.4 hours. Using the Turbo preset with `--steps 10` reduces this to
~1.1 hours. Previous runs have completed on CPU on this machine.

---

## Weight Caching

Pipeline weights are cached in `_shape_cache` (keyed by model path +
subfolder + device + dtype). In batch mode, weights survive across
creatures — the heavy model load only happens once.

---

## Output

The pipeline call returns a trimesh object which is immediately exported
to a temporary GLB file. This becomes `current_glb` — the working file
that flows through scale normalization, decimation, leg fix, and texture
bake.

---

## Post-Shape Processing

Three steps run immediately after shape generation:

### Scale Normalization (step 4b)

- Measures Z-axis bounding box height
- Applies uniform scale to match `--height` target
- Must run before leg fix and rigging (they depend on correct scale)

### Mesh Decimation (step 4c)

- Target: 100K faces
- Prevents vertex count explosion during GLB UV-seam splitting (~3x
  inflation), keeping final vertex count under the 500K acceptance cap
- Strategy: try trimesh first (fast), fall back to Blender Decimate

### Leg Fix (step 5)

- Scans lower 38% of mesh for leg columns
- Fixes flat legs (depth/width < 0.35) by splitting or thickening
- Profile-aware (quadruped vs humanoid)

---

## Key File

`src/model_generator_cli/pipeline.py:53-69` — weight loading and caching
`src/model_generator_cli/pipeline.py:311-349` — shape generation call
