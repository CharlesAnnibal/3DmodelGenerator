---
status: done
---

# MGC-8 — FBX Export & Rig Manifest

## Problem
The generator outputs GLB only. Mixamo — the fastest free animation source for humanoid creatures — requires FBX or OBJ input. Unity's Humanoid avatar auto-mapping works from bone names, but those names are only discoverable by opening the GLB in a tool; nothing in the output documents them. This forces manual inspection for every new creature imported into the Arena.

## Goal
The pipeline additionally writes an FBX of each rigged model and a `rig_manifest.json` alongside it. The FBX enables direct Mixamo upload. The manifest documents the rig profile, bone names, and hierarchy so Unity avatar configuration and animation retargeting are predictable and reproducible.

## Deliverables

1. `output/{name}/3dmodel/{name}_rigged.fbx` — rigged untextured mesh
2. `output/{name}/3dmodel/{name}_textured_rigged.fbx` — rigged textured mesh
3. `output/{name}/3dmodel/{name}_rig_manifest.json` — rig profile + full bone list with parent names

## Scope

### In scope
- FBX export from the same Blender session that builds the rig (no second Blender invocation)
- `rig_manifest.json` written by the Blender script, saved by the pipeline
- `--no-fbx` flag to skip FBX export (for faster iteration when not needed)
- FBX settings: `add_leaf_bones=False`, `bake_anim=False` (static bind pose only)

### Out of scope
- T-pose normalization — Hunyuan meshes come in natural pose; Mixamo's auto-rigger handles re-rigging from any pose
- Animation baking into FBX
- OBJ export
- Changing the GLB output — FBX is additive

## Acceptance criteria
- [ ] `{name}_rigged.fbx` is present in output after a standard run
- [ ] `{name}_textured_rigged.fbx` is present in output after a standard run
- [ ] `{name}_rig_manifest.json` lists all bone names and their parents
- [ ] `--no-fbx` skips FBX export; GLB output is unchanged
- [ ] Uploading `{name}_rigged.fbx` to Mixamo shows the correct skeleton preview
- [ ] `rig_manifest.json` contains `profile`, `bone_count`, and `bones` array with `name`/`parent` per entry

## Constraints
- FBX export must happen inside the existing Blender subprocess — no additional Blender launch
- `rig_manifest.json` must be valid JSON readable without Blender or trimesh
