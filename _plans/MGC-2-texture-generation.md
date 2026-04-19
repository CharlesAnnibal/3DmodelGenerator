# Plan: MGC-2 — Multi-View Texture Baking

This is the most complex step in the pipeline. It takes a bare grey mesh and
projects the original reference images onto it to produce a coloured albedo
texture using pure-Python triplanar projection.

## Affected files

| File | Change |
|---|---|
| `modelGenerator/scripts/texture_bake_python.py` | `_triplanar_bake()` — the validated texture approach |
| `modelGeneratorCLI/src/model_generator_cli/pipeline.py` | Image pre-processing (`_white_bg_to_alpha`, `_crop_to_content`, `_sample_avg_color`), bake orchestration in steps 7-8. **Needs update: wire in `texture_bake_python.py` instead of Blender bake** |
| `modelGenerator/scripts/texture_bake_blender.py` | Legacy Blender-based bake (not recommended, kept as reference) |

## Implementation steps

- [x] Step 1 — Implement `_white_bg_to_alpha()` for background removal preserving light-coloured creatures
- [x] Step 2 — Implement `_crop_to_content()` to trim reference images to creature bounding box
- [x] Step 3 — Implement `_sample_avg_color()` / `_dominant_color()` for base coat fallback colour
- [x] Step 4 — Implement triplanar face assignment: front/back/side by face normal with side margin 0.50
- [x] Step 5 — Build composite texture: 3 vertical strips (front | back | side), pre-filled with base coat
- [x] Step 6 — Compute per-face-corner UVs mapping into the composite strip for each face's assigned view
- [x] Step 7 — Handle side mirroring: flip U for faces with normal.x < 0
- [x] Step 8 — Export GLB with composite texture embedded + GLTF with `KHR_materials_unlit` patch
- [x] Step 9 — Wire `texture_bake_python.py` into the pipeline (replace Blender bake subprocess call)
- [x] Step 10 — Validate: "awesome! lgtm" confirmation on triplanar output

---

## Overview

```
Reference images (front, back, side)
        │
        ▼
┌───────────────────────┐
│  Pre-process images   │  white-to-alpha, crop to content
│  (pipeline.py)        │
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│  texture_bake_python  │  pure Python, no Blender
│                       │
│  1. Load mesh         │  trimesh, triangle soup
│  2. Face normals      │  assign each face to front/back/side
│  3. Composite texture │  3 strips pre-filled with base coat
│  4. Per-face UVs      │  project into composite strip
│  5. Export            │  GLB + GLTF with unlit patch
└───────────┬───────────┘
            │
            ▼
      {name}_textured.glb   (composite texture embedded)
      {name}_textured.gltf  (KHR_materials_unlit)
      {name}.png            (composite albedo)
```

---

## Why Triplanar Projection (Not Blender Bake)

Three approaches were tried and rejected:

| Approach | Result |
|---|---|
| **xatlas UV atlas** | Too many tiny chart islands on Hunyuan meshes — shattered-glass texture |
| **Vertex colors** | Viewer-dependent rendering (glTF Tools + PBR washes out), limited resolution |
| **Blender bake** (`texture_bake_blender.py`) | Slow Python UV projection loop times out on 80K+ face meshes |

Triplanar avoids atlas fragmentation by assigning UVs that project directly from
3D to the reference image. Each face samples its dominant view's image at full
resolution. No unwrap step at all. Triangle soup is fine — per-face-corner UVs.

---

## Step-by-Step Detail

### Image Pre-Processing (pipeline.py)

1. **White-to-alpha** (`_white_bg_to_alpha`): near-white (>= 240) and drop-shadow
   (grey >= 185, low saturation) pixels → transparent. Preferred over rembg because
   rembg destroys alpha on light-coloured cartoon creatures.

2. **Crop to content** (`_crop_to_content`): crop RGBA to opaque bounding box + 3%
   padding. Ensures the creature fills the projection range.

3. **Base coat** (`_dominant_color`): mean sRGB of opaque pixels in front image. Used
   to pre-fill the composite so uncovered surfaces get a reasonable colour.

### Coordinate System

Hunyuan3D: **Y-up, creature faces +Z**.

| View | Camera direction | U axis (image right) | V axis (image up) |
|------|-----------------|---------------------|-------------------|
| `front` | +Z | +X | +Y |
| `back` | -Z | -X | +Y |
| `side` | +X | -Z | +Y |

### Face Assignment

```python
abs_x = |normal.x|
abs_z = |normal.z|
side_margin = 0.50

is_side  = abs_x > (abs_z + side_margin)
is_front = (!is_side) AND (normal.z >= 0)
is_back  = (!is_side) AND (normal.z < 0)
```

**Side margin 0.50** is critical: prevents side-view features (profile eye) from
bleeding onto the face. Anything ambiguous → front/back (safer).

### Composite Texture

```
┌─────────┬─────────┬─────────┐
│  front  │  back   │  side   │
│ strip 0 │ strip 1 │ strip 2 │
└─────────┴─────────┴─────────┘
```

- 3 strips, each `tex_size / 3` wide
- Images scaled to fit within strip (preserve aspect ratio), centered
- Pre-filled with base coat colour (opaque)

### Per-Face UV Computation

For each face assigned to view `v`:

1. Project mesh bbox corners onto view's U/V axes → world-space extents
2. Project each face-corner vertex: `u = (vertex . U - u_min) / range`
3. Side faces with `normal.x < 0`: mirror U (`u = 1 - u`)
4. Map from [0,1] within view → pixel position within composite strip
5. Convert to texture-space UV: `u_tex = (pixel_offset + u * img_width) / tex_size`

### Export

**GLB**: trimesh export with per-face-corner UVs and composite PNG embedded.

**GLTF + unlit patch**: JSON post-processing adds:
- `extensionsUsed: ["KHR_materials_unlit"]`
- `metallicFactor: 0.0`, `roughnessFactor: 1.0`
- `extensions: { "KHR_materials_unlit": {} }`

Ensures full-intensity display without PBR lighting darkening colours.

---

## Data Flow: Pipeline ↔ Texture Script

```
pipeline.py                          texture_bake_python.py
───────────                          ──────────────────────
  │
  ├─ _white_bg_to_alpha(img)
  ├─ _crop_to_content(img)
  ├─ Save temp PNGs to disk
  │
  ├─ Invoke texture_bake_python.py:
  │    py -3 texture_bake_python.py
  │        <input_glb> <out_glb> <out_png> <size>
  │        front=<path> back=<path> side=<path>
  │                                    │
  │                                    ├─ Load mesh (trimesh)
  │                                    ├─ Compute face normals
  │                                    ├─ Assign faces to views
  │                                    ├─ Build composite texture
  │                                    ├─ Compute per-face UVs
  │                                    ├─ Export GLB + GLTF
  │                                    ├─ Patch KHR_materials_unlit
  │                                    │
  ├─ Copy GLB → {name}_textured.glb
  ├─ Copy PNG → textures/{name}.png
  ├─ Clean up temp files
```

---

## Completed

**Step 9** (done 2026-04-16): Pipeline rewired from `texture_bake_blender.py` to
`texture_bake_python.py`. Calls `sys.executable` directly — no Blender needed for
texture baking. Log filter updated from `[texture_bake]` to `[bake_py]`.

---

## Tuning Parameters

| Parameter | Location | Default | Effect |
|-----------|----------|---------|--------|
| `texture_size` | CLI `--texture-size` | 2048 | Composite texture resolution |
| `side_margin` | `texture_bake_python.py:413` | 0.50 | How aggressively side is excluded from front-facing surfaces |
| `white_threshold` | `_white_bg_to_alpha` | 240 | White-to-alpha cutoff |
| `shadow_brightness` | `_white_bg_to_alpha` | 185 | Drop shadow removal threshold |

---

## Common Failure Modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Profile eye on face | Side margin too low | Increase `side_margin` (currently 0.50) |
| Washed-out in viewers | PBR lighting on albedo | `KHR_materials_unlit` patch |
| Creature off-centre in strip | Large white margins in input | `_crop_to_content` trims to bounding box |
| Shattered-glass texture | Using xatlas instead of triplanar | Don't use xatlas on Hunyuan meshes |
| 30-minute timeout | Using Blender bake on large mesh | Use triplanar Python instead |

---

## Key Files

| File | Role |
|------|------|
| `modelGenerator/scripts/texture_bake_python.py` | `_triplanar_bake()` — validated approach |
| `modelGeneratorCLI/src/model_generator_cli/pipeline.py:451-505` | Bake orchestration (needs rewire to Python script) |
| `modelGenerator/scripts/texture_bake_blender.py` | Legacy Blender bake (not recommended) |
