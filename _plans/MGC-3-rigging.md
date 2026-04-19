# Plan: MGC-3 — Auto-Rigging

Adds a skeleton (armature) and vertex weights to the mesh so it can be
animated in a game engine.

## Affected files

| File | Change |
|---|---|
| `modelGenerator/scripts/autorig_humanoid_blender.py` | Headless Blender script: profile detection, armature building, weight binding, export |
| `modelGenerator/src/model_generator/blender_tools.py` | `autorig_via_blender()` subprocess wrapper |
| `src/model_generator_cli/pipeline.py` | Rig calls in steps 6 (untextured) and 9 (textured) |
| `src/model_generator_cli/__main__.py` | `--rig-profile`, `--no-rig` flags |

## Implementation steps

- [x] Step 1 — Implement `_detect_limb_columns()` for leg cluster detection
- [x] Step 2 — Implement auto-detection logic: limb count + width/height ratio → profile
- [x] Step 3 — Implement humanoid armature: bone positions as fractions of mesh height
- [x] Step 4 — Implement quadruped armature: 4-leg placement from detected clusters
- [x] Step 5 — Implement serpentine armature: 8-segment Y-axis spine chain
- [x] Step 6 — Weight binding via `ARMATURE_AUTO` envelope weights
- [x] Step 7 — Export with skins enabled (GLB/FBX)
- [x] Step 8 — Wire into pipeline: rig untextured (step 6) and textured (step 9)

---

## When It Runs

Rigging runs **twice** per creature:

| Call | Input | Output |
|------|-------|--------|
| Step 6 | raw/leg-fixed GLB (untextured) | `{name}.glb` |
| Step 9 | textured GLB (post-bake) | `{name}_textured_rigged.glb` |

Skipped entirely with `--no-rig`.

---

## Profile Detection

Controlled by `--rig-profile` (default `auto`).

### Auto-detection logic

1. Detect leg columns in lower 35% of mesh height
2. Compute `width / height` of full bounding box
3. Decision:
   - No limbs OR width/height > 3.0 → **serpentine**
   - >= 4 limbs → **quadruped**
   - Otherwise → **humanoid**

---

## Armature Layouts

### Humanoid (~20 bones)

```
           Head
            │
           Neck
            │
          Spine
         /  │  \
   L.Arm  Hips  R.Arm
   (3 bones each)
          / \
       L.Leg  R.Leg
       (3 bones each)
```

Bone positions are fractions of mesh height (Z-axis):
- Hips: 53% height
- Spine: 64-74%
- Neck: 74-84%
- Head: 84-100%
- Legs: 53% down to ~2%

Arm length: `max(18% height, 22% width)`.
Leg X positions from detected limb clusters; fallback to symmetric offset.

### Quadruped (~20 bones)

Same spine/neck/head as humanoid. Four legs placed at detected limb
cluster positions:
- Front pair → parented to Spine
- Back pair → parented to Hips

### Serpentine (8 bones)

8-segment spine chain along Y axis (`Spine01`…`Spine08`).
No legs or arms.

---

## Weight Binding

Uses `bpy.ops.object.parent_set(type="ARMATURE_AUTO")` — Blender's
built-in automatic envelope weights. No manual weight painting.

---

## Pre-Processing (before armature)

1. Join all mesh objects into one
2. Apply transforms
3. `remove_doubles` threshold 0.0005
4. `delete_loose` (isolated verts/edges/faces)
5. `normals_make_consistent` (flip inward normals outward)

---

## Export

- GLB: `export_scene.gltf` with `export_apply=True`, `export_skins=True`
- FBX fallback: `export_scene.fbx` with `add_leaf_bones=False`
- Pipeline always requests GLB

---

## Limitations

- One bone per limb segment (no twist bones, no IK)
- Envelope weights only (no heat diffusion, no custom groups)
- Serpentine rig at fixed Z regardless of body shape
- No tail, wing, or tentacle support

---

## Key File

`modelGenerator/scripts/autorig_humanoid_blender.py`
