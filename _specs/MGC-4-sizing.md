---
status: done
---

# MGC-4 — Scale Normalization / Sizing

## Problem
Hunyuan3D-2 outputs meshes in a normalized bounding box (~+-1 unit) regardless of the creature's intended real-world size. Two creatures generated from the same preset can have different bounding-box heights, and none reflect the intended in-game scale.

## Goal
Normalize every generated mesh to a target height (in metres) so creatures are consistently sized for the game engine. Support named presets (small/medium/big/huge) and arbitrary decimal values.

## Scope

### In scope
- Size presets: small=0.3m, medium=1.0m, big=2.5m, huge=5.0m
- `--height` flag accepting decimal or preset name
- Uniform scale applied after raw GLB export, before leg-fix and rigging
- Acceptance check: height within +/-10% of target (M-09)
- Convention: 1 unit = 1 metre (glTF standard)

### Out of scope
- Non-uniform scaling
- Automatic size estimation from reference image

## Current state
Documents the scale convention, current state, and the normalization system.

---

## 1. Scale Convention

**1 unit = 1 metre** (glTF/GLB standard).

| Engine / Tool | Unit |
|---------------|------|
| glTF / GLB spec | 1 unit = 1 m |
| Blender default | 1 unit = 1 m |
| Unity import | 1 unit = 1 m (GLB imported 1:1) |
| Unreal Engine | 1 unit = 1 cm (a 1 m GLB = 100 UU tall) |

Coordinate system: **Z-up** in Blender and trimesh post-load. glTF stores Y-up; the
GLTF exporter rotates automatically. The pipeline always measures height along Z.

---

## 2. Current State (no normalization)

Hunyuan3D-2 outputs meshes in a **normalized bounding box** — roughly ±1 unit around
the origin, independent of the input image pixel dimensions. The image affects shape
and detail, **not** absolute scale.

There is no size-normalization step in the pipeline today. As a result:
- Creature scale varies between runs and between different creatures.
- Two creatures generated from the same preset can differ in bounding-box height.
- Downstream tools (auto-rig, acceptance checks) operate on whatever scale the model
  happens to come out at.

---

## 3. Planned: Size Presets and `--height` Flag

The following system is planned (not yet implemented):

### CLI flags

| Flag                | Target height | Approximate real-world reference |
|---------------------|--------------|----------------------------------|
| `--small`           | 0.30 m       | Cat / small animal               |
| `--medium` (default)| 1.00 m       | Medium creature                  |
| `--big`             | 2.50 m       | Bear / large animal              |
| `--huge`            | 5.00 m       | Boss / giant creature            |

`--height <value>` accepts:
- A decimal number in metres (e.g. `--height 1.8`)
- One of the preset strings: `"small"`, `"medium"`, `"big"`, `"huge"`

The shorthand flags (`--small`, `--medium`, `--big`, `--huge`) are aliases for
`--height <preset>`. If both `--height` and a preset flag are given, `--height` wins.

Default when no flag is given: `--medium` (1.00 m).

### Normalization step

Inserted in the pipeline **after raw GLB export (step 4) and before leg-fix (step 5)**
so all downstream Blender scripts operate on correctly-scaled geometry:

1. Load the raw mesh. Compute axis-aligned bounding box.
2. `height = bbox_Z_max − bbox_Z_min` (Z is up in Blender / trimesh post-load).
3. `scale_factor = target_height / height`
4. Apply uniform scale to all vertex positions.
5. Export as the new `current_glb`.

### Acceptance check

| ID    | Check                              | Pass condition                          | Severity |
|-------|------------------------------------|-----------------------------------------|----------|
| M-09  | Creature height within target band | `abs(bbox_Z − target) / target ≤ 0.10` | HIGH     |

The tolerance is ±10 % of the target value for all presets.
