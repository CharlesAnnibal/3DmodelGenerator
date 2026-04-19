---
status: done
---

# MGC-2 — Multi-View Texture Baking

## Problem
Hunyuan3D-2 produces untextured grey meshes. The creature needs a coloured albedo texture that matches the original reference images to look correct in-game.

## Goal
Project front/back/side reference images onto the mesh surface using triplanar projection — each face samples directly from its dominant view's image in a composite texture. No UV atlas unwrap, no Blender dependency. Surfaces not covered by any view receive a base-coat colour sampled from the creature's average body colour.

## Scope

### In scope
- Pure-Python triplanar projection via `texture_bake_python.py` (validated approach)
- White-to-alpha background removal (preserving light-coloured creatures)
- Content-aware cropping of reference images
- Dominant-axis face assignment: front (+Z), back (-Z), side (+/-X)
- Side margin (0.50) to prevent profile-eye bleeding onto face
- Composite texture: front | back | side in 3 vertical strips
- `KHR_materials_unlit` GLTF patch for full-intensity display
- Per-face-corner UVs (triangle soup is fine)
- Base coat colour fill for the entire composite as fallback
- CLI `--texture-size` flag (512/1024/2048/4096)

### Out of scope
- Normal maps, roughness maps, metallic maps
- Distinct right-side image (side is mirrored for -X normals)
- Top/bottom view projection
- Perspective correction or parallax
- xatlas UV atlas (produces shattered-glass on Hunyuan meshes)
- Blender-based Cycles bake (times out on 80K+ face meshes)
- Vertex colors (viewer-dependent rendering, limited resolution)

## Approaches that failed

| Approach | Problem |
|---|---|
| xatlas UV atlas | Too many tiny chart islands on Hunyuan meshes — shattered-glass texture |
| Vertex colors | Viewer-dependent rendering (glTF Tools + PBR lighting washes colors out), limited resolution |
| Blender bake (`texture_bake_blender.py`) | Slow Python UV projection loop times out on 80K+ face meshes |

## Current state

The validated approach is the pure-Python triplanar projection implemented in
`modelGenerator/scripts/texture_bake_python.py` (`_triplanar_bake()`).

The pipeline (`pipeline.py`) calls `texture_bake_python.py` via subprocess
using `sys.executable`. Wired in on 2026-04-16.

---

## 1. Inputs

| Input | Source |
|-------|--------|
| Mesh GLB | `current_glb` at the time of baking (after decimation, before rigging) |
| Front image | `views["front"]` (required) |
| Back image | `views["back"]` (optional) |
| Side image | `views["left"]` or `views["right"]` (optional; aliased to `side`) |
| Texture size | `--texture-size` (default 2048) |

The pipeline sends only the views that exist. If no images are available, baking is
skipped and the untextured GLB is used as-is.

---

## 2. Image Pre-Processing

Each reference image goes through two transforms before projection:

1. **White-to-alpha** (`_white_bg_to_alpha`): Converts near-white pixels
   (all channels >= 240) and drop-shadow pixels (near-neutral grey >= 185)
   to transparent. Preferred over rembg because rembg destroys alpha on
   light-coloured cartoon creatures.

2. **Crop to content** (`_crop_to_content`): Crops the RGBA image to the
   bounding box of opaque pixels with 3% padding. Without this, a creature
   sitting in a small corner of a large image would waste most of the
   projection range on transparent pixels.

---

## 3. Coordinate System

Hunyuan3D convention: **Y-up**, creature faces **+Z**.

| View | Camera direction | U axis (image right) | V axis (image up) |
|------|-----------------|---------------------|-------------------|
| `front` | +Z | +X | +Y |
| `back` | -Z | -X | +Y |
| `side` | +X | -Z | +Y |

---

## 4. Triplanar Face Assignment

Each face is assigned to exactly one view based on its face normal:

```
abs_x = |normal.x|
abs_z = |normal.z|
side_margin = 0.50

is_side  = abs_x > (abs_z + side_margin)
is_front = (!is_side) AND (normal.z >= 0)
is_back  = (!is_side) AND (normal.z < 0)
```

The **side margin of 0.50** is critical — it prevents the side view from claiming
faces near the front of the creature. Without it, profile features (e.g. a side-view
eye) bleed onto the face. Anything ambiguous goes to front/back, which are safer.

For side faces with `normal.x < 0` (facing -X), the U coordinate is mirrored
(`u = 1.0 - u`) so both flanks use the same side image.

---

## 5. Composite Texture

The output texture is a single image divided into 3 vertical strips:

```
┌─────────┬─────────┬─────────┐
│         │         │         │
│  front  │  back   │  side   │
│         │         │         │
│ strip 0 │ strip 1 │ strip 2 │
└─────────┴─────────┴─────────┘
  0..1/3    1/3..2/3  2/3..1
```

- Each strip is `texture_size / 3` pixels wide, `texture_size` tall
- Reference images are scaled to fit within their strip (preserving aspect ratio)
  and centered
- The entire composite is pre-filled with the **base coat colour** (average opaque
  RGB from front image) so uncovered areas get a reasonable colour

---

## 6. Per-Face UV Computation

For each face assigned to view `v`:

1. Project the mesh bounding-box corners onto the view's U/V axes to get world-space
   extents (`u_min`, `u_max`, `v_min`, `v_max`)
2. Project each face-corner vertex: `u = (vertex . U_axis - u_min) / (u_max - u_min)`
3. Map `u` from [0,1] within the view to pixel coordinates within the strip, accounting
   for the image's actual position (centered within the strip)
4. Convert to texture-space UV: `u_tex = (x_pixel_offset + u * image_width) / texture_size`

UVs are per-face-corner (triangle soup) — no shared vertices between faces. This avoids
any atlas unwrap step entirely.

---

## 7. Export

### GLB

Trimesh exports the textured mesh with per-face-corner UVs and the composite PNG
embedded as the texture.

### GLTF + Unlit Patch

A separate GLTF is exported and then patched with JSON manipulation:

- `extensionsUsed` gets `KHR_materials_unlit`
- Every material gets:
  - `pbrMetallicRoughness.metallicFactor = 0.0`
  - `pbrMetallicRoughness.roughnessFactor = 1.0`
  - `extensions: { "KHR_materials_unlit": {} }`

This ensures glTF Tools and PBR viewers display the texture at full intensity
without lighting darkening the colours.

---

## 8. Outputs

```
output/{name}/3dmodel/
  {name}_textured.glb          ← textured mesh (no rig), composite texture embedded
  {name}_textured.gltf         ← GLTF variant with KHR_materials_unlit
output/{name}/textures/
  {name}.png                   ← composite albedo PNG
```

---

## 9. Tuning Parameters

| Parameter | Location | Default | Effect |
|-----------|----------|---------|--------|
| `texture_size` | CLI `--texture-size` | 2048 | Composite texture resolution |
| `side_margin` | `texture_bake_python.py:413` | 0.50 | How aggressively side is excluded from front-facing surfaces |
| `_VIS_THRESHOLD` | `texture_bake_python.py:32` | 0.05 | Min dot product for xatlas path (unused in triplanar) |
| `_FALLOFF_POWER` | `texture_bake_python.py:33` | 4 | Weight falloff exponent for xatlas path (unused in triplanar) |
| `white_threshold` | `_white_bg_to_alpha` | 240 | White-to-alpha cutoff |
| `shadow_brightness` | `_white_bg_to_alpha` | 185 | Drop shadow removal threshold |

---

## 10. Limitations (current)

- Only albedo — no normal map, roughness, or metallic maps
- Side image is mirrored for -X faces; no distinct right-side image
- No top or bottom view projection — those surfaces get base coat only
- Purely orthographic — no perspective correction
- Triangle soup output (~3x vertex count vs shared vertices)
- Strip layout wastes some texture space if reference images have very different aspect ratios

---

## 11. Key Files

| File | Role |
|------|------|
| `modelGenerator/scripts/texture_bake_python.py` | `_triplanar_bake()` — validated approach |
| `modelGeneratorCLI/src/model_generator_cli/pipeline.py:451-505` | Orchestrates bake (currently wired to Blender, needs update) |
| `modelGenerator/scripts/texture_bake_blender.py` | Blender-based bake (legacy, not recommended) |
