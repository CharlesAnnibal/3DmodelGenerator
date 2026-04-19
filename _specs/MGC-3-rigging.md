---
status: done
---

# MGC-3 — Auto-Rigging

## Problem
Generated meshes have no skeleton. Without an armature and vertex weights, the creature cannot be animated in a game engine.

## Goal
Automatically detect the creature's body type (humanoid, quadruped, serpentine), build an appropriate skeleton, and bind vertex weights using Blender's envelope-based auto-weighting.

## Scope

### In scope
- Auto-detection of rig profile from mesh geometry
- Humanoid armature (~20 bones: spine, arms, legs)
- Quadruped armature (~20 bones: spine, 4 legs)
- Serpentine armature (8-segment spine chain)
- Limb column detection for leg placement
- Automatic envelope weight binding
- CLI `--rig-profile` flag (auto/humanoid/quadruped/serpentine)
- Runs twice: once untextured, once on textured mesh

### Out of scope
- Twist bones, IK targets
- Heat diffusion or custom weight painting
- Tail, wing, or tentacle support
- Independent rig editing endpoints

## Current state
Documents the auto-rigging step as it is implemented today in
`modelGenerator/scripts/autorig_humanoid_blender.py`.

---

## 1. When It Runs

Rigging runs **twice** per creature (unless `--no-rig` is passed):

| Call | Input | Output |
|------|-------|--------|
| Step 6 of pipeline | raw / leg-fixed GLB | `{name}.glb` (untextured, rigged) |
| Step 9 of pipeline | textured GLB | `{name}_textured_rigged.glb` |

The untextured rigged GLB is written to `output/{name}/3dmodel/` and is the model
loaded by the acceptance test.

---

## 2. Pre-Processing

Before building the armature:

1. **Join meshes** — all MESH objects in the scene are joined into one. Transforms
   are applied (`location=True, rotation=True, scale=True`).
2. **Clean mesh**:
   - `remove_doubles` threshold `0.0005` — welds near-duplicate vertices
   - `delete_loose` — removes isolated verts/edges/faces
   - `normals_make_consistent(inside=False)` — flips inward-pointing normals outward

---

## 3. Profile Selection

Controlled by `--rig-profile` (default `auto`). Choices: `auto`, `humanoid`,
`quadruped`, `serpentine`.

### Auto-detection logic

1. Run `_detect_limb_columns` with `z_cutoff_ratio=0.35` to count leg clusters.
2. Compute `width / height` of the full mesh bounding box.
3. Decision:
   - `n_limbs == 0` **or** `width / height > 3.0` → `serpentine`
   - `n_limbs >= 4` → `quadruped`
   - otherwise → `humanoid`

### Limb column detection (shared by all profiles)

Scans vertices below `z_cutoff_ratio × mesh_height`. Groups them into clusters using
an incremental centroid algorithm with `merge_dist = 18 % × max(width, depth)`.
Clusters with fewer than `max(3, total_low_verts / 20)` points are discarded.
Returns `(cx, cy)` centre per surviving cluster, sorted front-to-back then left-to-right.

---

## 4. Humanoid Armature

Bone positions as fractions of mesh height (`h = max_Z − min_Z`), Z-up:

| Bone            | Head Z           | Tail Z           | Parent   |
|-----------------|------------------|------------------|----------|
| Hips            | `min_Z + 0.53 h` | `min_Z + 0.64 h` | root     |
| Spine           | `min_Z + 0.64 h` | `min_Z + 0.74 h` | Hips     |
| Neck            | `min_Z + 0.74 h` | `min_Z + 0.84 h` | Spine    |
| Head            | `min_Z + 0.84 h` | `max_Z`          | Neck     |
| {Side}Shoulder  | `min_Z + 0.74 h` | shoulder offset  | Spine    |
| {Side}UpperArm  | shoulder         | +60 % arm_len    | Shoulder |
| {Side}LowerArm  | upper end        | +50 % arm_len    | UpperArm |
| {Side}Hand      | lower end        | +20 % arm_len    | LowerArm |
| {Side}UpperLeg  | `min_Z + 0.53 h` | `min_Z + 0.28 h` | Hips     |
| {Side}LowerLeg  | `min_Z + 0.28 h` | `min_Z + 0.06 h` | UpperLeg |
| {Side}Foot      | `min_Z + 0.06 h` | `min_Z + 0.02 h` | LowerLeg |

Arm length: `max(0.18 h, 0.22 w)`.  
Leg X positions: taken from the two outermost detected limb clusters. Fallback if
fewer than 2 clusters: `± max(0.08 w, 0.05 h)` from centre.

---

## 5. Quadruped Armature

Same Z proportions as humanoid for spine/neck/head. Four legs placed at the four
detected limb cluster positions:

| Group      | Parent |
|------------|--------|
| FrontLeft  | Spine  |
| FrontRight | Spine  |
| BackLeft   | Hips   |
| BackRight  | Hips   |

Each leg: UpperLeg → LowerLeg → Foot, same Z fractions as humanoid.

Fallback if fewer than 4 clusters detected: uses front/back pair symmetrically, or
falls back to fixed offsets from centre.

---

## 6. Serpentine Armature

8-segment spine chain running along the Y axis from `min_Y` to `max_Y` at
`Z = min_Z + 0.55 h`. Bones: `Spine01` … `Spine08`, each parented to the previous.
No legs or arms.

---

## 7. Weight Binding

Uses `bpy.ops.object.parent_set(type="ARMATURE_AUTO")` — Blender's built-in
automatic envelope weights. No manual weight painting or heat diffusion.

---

## 8. Export

- Output extension `.glb` / `.gltf` → `export_scene.gltf` with `export_apply=True`,
  `export_skins=True`.
- Output extension `.fbx` → `export_scene.fbx` with `apply_unit_scale=True`,
  `add_leaf_bones=False`, `bake_space_transform=False`.
- The pipeline always requests GLB output.

---

## 9. Limitations (current)

- Only one bone per limb segment (no twist bones, no IK targets).
- Weights are purely envelope-based — no heat diffusion, no custom groups.
- The serpentine rig always places bones at a fixed Z regardless of actual body shape.
- No tail, wing, or tentacle support.
