## General Plan — Model Generator CLI

### Objective

Generate game-ready 3D creature models from 2D reference images. The pipeline handles shape generation, texture baking, auto-rigging, and quality validation.

### What is already done

- CLI entry point with batch processing and per-creature flags
- Hunyuan3D-2 shape generation (single-view and multi-view)
- Multi-view orthographic texture baking via Blender Cycles
- Auto-rigging with humanoid/quadruped/serpentine profile detection
- Scale normalization with size presets
- Mesh decimation (trimesh + Blender fallback)
- Merged-leg fix via Blender
- Background removal via rembg
- Acceptance test suite with 28 quality checks
- Progress bars with historical ETA
- Input image renaming after successful generation

### Tickets

| Ticket | Title | Status |
|---|---|---|
| MGC-1 | 3D Model Shape Generation | done |
| MGC-2 | Multi-View Texture Baking | done |
| MGC-3 | Auto-Rigging | done |
| MGC-4 | Scale Normalization / Sizing | done |
| MGC-5 | Acceptance Test Suite | done |

### Open questions

- Should the pipeline add a CUDA availability check and warn/abort early on CPU?
- Is there a need for a web UI or is this purely CLI?
- Should the pipeline support re-running only specific steps (e.g. re-bake texture without re-generating shape)?

---

End-to-end flow for generating a 3D creature model from reference images.

---

## Pipeline Steps (in order)

```
Input images (front, back, side)
    │
    ▼
 1. Load images
    │
    ▼
 2. Background removal (rembg)
    │
    ▼
 3. Shape generation (Hunyuan3D-2)  ← slowest step, needs GPU ideally
    │
    ▼
 4a. Export raw GLB (temp)
    │
    ▼
 4b. Scale normalization (--height)
    │
    ▼
 4c. Mesh decimation (target 100K faces)
    │
    ▼
 5. Fix merged legs (Blender)
    │
    ▼
 6. Auto-rig untextured model (Blender) → {name}.glb
    │
    ▼
 7. Texture bake (Blender Cycles)   ← see texture-generation.md
    │
    ▼
 8. Save textured GLB               → {name}_textured.glb
    │
    ▼
 9. Auto-rig textured model         → {name}_textured_rigged.glb
    │
    ▼
10. Acceptance test                  → acceptance.json
    │
    ▼
11. Cleanup temp files
    │
    ▼
12. Mark input images as _processed
```

---

## Step Details

### 1. Load Images (pipeline.py:293-299)

- Reads each view from `input/{name}/` as RGBA PIL images
- Supported views: `front`, `back`, `side`, `left`, `right`
- Supported formats: `.png`, `.jpg`, `.jpeg`, `.webp`
- If `side` is present but `left` is not, `side` is aliased to `left`
- Originals are kept for texture baking (rembg can destroy alpha)

### 2. Background Removal (pipeline.py:306-308)

- Uses rembg (`maybe_rembg`) on each view
- Skipped with `--no-rembg`
- Produces RGBA images with transparent backgrounds

### 3. Shape Generation (pipeline.py:311-349)

**Multi-view path (>= 2 views):**
- Uses `tencent/Hunyuan3D-2mv` model
- Deduplicates mirrored views first
- Rejects front+back only (invents extra limbs)
- Minimum: front + left/right

**Single-view path (1 view):**
- Three presets: Quality (20 steps), Turbo (10 steps), Mini (low VRAM)
- Default CLI: 40 steps, octree 260, 20K chunks

**Hardware:**
- CUDA available → fp16 on GPU (~2 min)
- CPU only → fp32 (~4+ hours with default steps)
- Pipeline weights cached between creatures in batch

### 4a. Raw GLB Export (pipeline.py:352-357)

Trimesh object exported to temp GLB. This is `current_glb` — the working
file that flows through subsequent steps.

### 4b. Scale Normalization (pipeline.py:359-379)

- Loads mesh, measures Z-axis bounding box height
- Applies uniform scale: `target_height / bbox_Z`
- Presets: small=0.3m, medium=1.0m, big=2.5m, huge=5.0m
- `--height` accepts decimal metres or preset name

### 4c. Mesh Decimation (pipeline.py:385-425)

Target: 100K faces (prevents vertex explosion during GLB UV-seam splitting).

Strategy:
1. Try trimesh `simplify_quadric_decimation` (fast, in-process)
2. If trimesh fails/no effect → fall back to Blender Decimate modifier

### 5. Fix Merged Legs (pipeline.py:428-438)

- Blender script scans lower 38% of mesh for leg columns
- Flat legs (depth/width < 0.35) are split or thickened
- Profile-aware: quadruped vs humanoid
- Skipped with `--no-fix-legs`

### 6. Auto-Rig Untextured (pipeline.py:440-449)

- Auto-detects profile: humanoid, quadruped, or serpentine
- Blender envelope weights (`ARMATURE_AUTO`)
- Output: `{name}.glb` in `output/{name}/3dmodel/`

### 7. Texture Bake (pipeline.py:451-505)

See `_plans/texture-generation.md` for full detail.

- Uses original (pre-rembg) images with white-to-alpha conversion
- Multi-view normal-weighted projection via Blender Cycles
- Base coat fallback for uncovered surfaces
- Fallback: CPU texture projection if Blender fails

### 8. Save Textured GLB (pipeline.py:508-510)

Copies textured GLB to `{name}_textured.glb`.

### 9. Auto-Rig Textured (pipeline.py:513-520)

Same rigging process as step 6, but on the textured mesh.
Output: `{name}_textured_rigged.glb` — the final deliverable.

### 10. Acceptance Test (pipeline.py:524-553)

See `_specs/acceptance-test.md` for full check list.

Categories:
- File checks (F-01 to F-06)
- Mesh quality (M-01 to M-10)
- Texture quality (T-01 to T-05)
- Rigging integrity (G-01 to G-05)
- Render-based visual checks (R-01 to R-08)

Pass criteria: zero CRITICAL failures AND <= 2 HIGH failures.

### 11. Cleanup (pipeline.py:562-564)

All temp files (raw GLB, scaled GLB, decimated GLB, etc.) deleted.

### 12. Mark Processed (__main__.py:157-165)

Input images renamed: `front.png` → `front_processed.png`.
**Only runs after successful completion** — if the pipeline throws an
exception, images stay unchanged (this is the signal that generation
failed).

---

## Output Structure

```
output/{name}/
  3dmodel/
    {name}.glb                    ← untextured, rigged
    {name}_textured.glb           ← textured, not rigged
    {name}_textured_rigged.glb    ← textured + rigged (final)
  textures/
    {name}.png                    ← baked albedo
  renders/                        ← generated by acceptance test
    front.png, back.png, left.png, right.png, top.png, three_quarter.png
  acceptance.json                 ← test results
```

---

## CLI Flags

| Flag | Default | Effect |
|------|---------|--------|
| `--input-dir` | `./input` | Where to scan for creature folders |
| `--output-dir` | `./output` | Where to write results |
| `--preset` | Quality | Shape gen model selection |
| `--steps` | 40 | Diffusion sampling steps |
| `--octree-resolution` | 260 | Mesh extraction resolution |
| `--num-chunks` | 20000 | GPU memory chunking |
| `--seed` | 12345 | Reproducibility seed |
| `--texture-size` | 2048 | Albedo resolution (512/1024/2048/4096) |
| `--rig-profile` | auto | Rig type (auto/humanoid/quadruped/serpentine) |
| `--height` | medium (1.0m) | Target height in metres or preset |
| `--creature` | all | Process only this creature |
| `--no-rembg` | | Skip background removal |
| `--no-texture` | | Skip texture baking |
| `--no-fix-legs` | | Skip leg fix |
| `--no-rig` | | Skip auto-rigging |
| `--no-acceptance` | | Skip acceptance checks |
| `--strict` | | Treat acceptance failure as hard error |

---

## Key Files

| File | Role |
|------|------|
| `src/model_generator_cli/__main__.py` | CLI entry point, creature scanning, batch loop |
| `src/model_generator_cli/pipeline.py` | Per-creature pipeline orchestration |
| `src/model_generator_cli/progress.py` | Terminal progress bars with historical ETA |
| `src/model_generator_cli/acceptance.py` | Post-generation quality checks |
| `modelGenerator/scripts/texture_bake_blender.py` | Headless Blender texture bake |
| `modelGenerator/scripts/render_views_blender.py` | Headless Blender render for acceptance |
| `modelGenerator/src/model_generator/blender_tools.py` | Blender utilities (find exe, rig, decimate, leg fix) |
| `modelGenerator/src/model_generator/image_utils.py` | rembg, mirrored-view dedup |

---

## Environment Requirements

- Python 3.10+
- PyTorch (CPU or CUDA)
- Hunyuan3D-2 (via hy3dgen)
- Blender (on PATH or auto-detected) — for texture bake, leg fix, rig, renders
- trimesh, Pillow, tqdm, numpy
- Optional: pygltflib (for rig acceptance checks), rembg
