# Plan: MGC-8 — FBX Export & Rig Manifest

Adds FBX output and a JSON bone manifest to the rigging step so creatures
can be uploaded directly to Mixamo and their rig structure is self-documenting.

## Affected files

| File | Change |
|---|---|
| `modelGenerator/scripts/autorig_humanoid_blender.py` | Export FBX after GLB; write `rig_manifest.json` |
| `modelGenerator/src/model_generator/blender_tools.py` | `autorig_via_blender()` returns FBX path + manifest path; accept `export_fbx` flag |
| `src/model_generator_cli/pipeline.py` | Copy FBX + manifest to output dir in steps 6 and 9 |
| `src/model_generator_cli/__main__.py` | Add `--no-fbx` flag |

---

## Implementation steps

- [x] Step 1 — `autorig_humanoid_blender.py`: after GLB export, add FBX export
- [x] Step 2 — `autorig_humanoid_blender.py`: write `rig_manifest.json` to temp dir
- [x] Step 3 — `blender_tools.py`: update `autorig_via_blender()` signature and return value
- [x] Step 4 — `pipeline.py`: copy FBX + manifest to output dir in step 6 (untextured rig)
- [x] Step 5 — `pipeline.py`: copy FBX + manifest to output dir in step 9 (textured rig)
- [x] Step 6 — `__main__.py`: add `--no-fbx` flag; pass through to pipeline

---

## Step 1 — FBX export in the Blender script

In `autorig_humanoid_blender.py`, the script currently ends with:

```python
bpy.ops.export_scene.gltf(
    filepath=str(out_path),
    export_format="GLB",
    export_apply=True,
    export_skins=True,
)
```

Add immediately after:

```python
if export_fbx:
    fbx_path = out_path.with_suffix(".fbx")
    bpy.ops.export_scene.fbx(
        filepath=str(fbx_path),
        add_leaf_bones=False,
        bake_anim=False,
        use_selection=False,
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_NONE",
    )
```

The `export_fbx` flag comes from a new CLI arg parsed alongside the existing `profile` arg:

```
blender --background --python autorig_humanoid_blender.py -- in.glb out.glb [profile] [--no-fbx]
```

---

## Step 2 — `rig_manifest.json`

After the armature is built (before export), collect bone data and write JSON:

```python
import json

manifest = {
    "profile": profile,
    "bone_count": len(arm_obj.data.bones),
    "bones": [
        {
            "name": b.name,
            "parent": b.parent.name if b.parent else None,
        }
        for b in arm_obj.data.bones
    ],
}
manifest_path = out_path.with_name(out_path.stem + "_rig_manifest.json")
manifest_path.write_text(json.dumps(manifest, indent=2))
```

---

## Step 3 — `blender_tools.py` signature change

Current:
```python
def autorig_via_blender(input_glb, rig_profile, *, scripts_dir=None) -> tuple[str | None, str]:
    """Returns (output_glb_path, message)"""
```

New:
```python
def autorig_via_blender(
    input_glb, rig_profile, *, scripts_dir=None, export_fbx=True
) -> tuple[str | None, str | None, str | None, str]:
    """Returns (glb_path, fbx_path, manifest_path, message)
    fbx_path and manifest_path are None if export_fbx=False or Blender failed."""
```

The subprocess call gains `"--no-fbx"` in args when `export_fbx=False`.

After Blender exits, check for sibling files:

```python
fbx_path = out_glb_path.with_suffix(".fbx")
manifest_path = out_glb_path.with_name(out_glb_path.stem + "_rig_manifest.json")
return (
    str(out_glb_path),
    str(fbx_path) if fbx_path.is_file() else None,
    str(manifest_path) if manifest_path.is_file() else None,
    "Auto-rig OK",
)
```

---

## Step 4 & 5 — Pipeline copies

In `pipeline.py`, update the two `autorig_via_blender` call sites.

Step 6 (untextured rig) — currently:
```python
rigged, rig_msg = autorig_via_blender(current_glb, rig_profile, ...)
if rigged is not None:
    shutil.copy2(rigged, model_dir / f"{name}.glb")
```

New:
```python
rigged, rigged_fbx, rig_manifest, rig_msg = autorig_via_blender(
    current_glb, rig_profile, export_fbx=auto_fbx, ...
)
if rigged is not None:
    shutil.copy2(rigged, model_dir / f"{name}.glb")
    if rigged_fbx:
        shutil.copy2(rigged_fbx, model_dir / f"{name}_rigged.fbx")
    if rig_manifest:
        shutil.copy2(rig_manifest, model_dir / f"{name}_rig_manifest.json")
```

Step 9 (textured rig) — same pattern, output name `{name}_textured_rigged.fbx`.

---

## Step 6 — `--no-fbx` flag

In `__main__.py`, alongside existing flags:

```python
parser.add_argument("--no-fbx", action="store_true", help="Skip FBX export")
```

Pass `auto_fbx = not args.no_fbx` into `generate_creature()`.

---

## Output structure after this change

```
output/{name}/3dmodel/
  {name}.glb                     ← untextured rigged (unchanged)
  {name}_rigged.fbx              ← NEW — for Mixamo upload
  {name}_rig_manifest.json       ← NEW — bone list
  {name}_textured.glb            ← textured unrigged (unchanged)
  {name}_textured_rigged.glb     ← textured rigged (unchanged)
  {name}_textured_rigged.fbx     ← NEW
```

---

## `rig_manifest.json` example (humanoid)

```json
{
  "profile": "humanoid",
  "bone_count": 20,
  "bones": [
    { "name": "Hips",          "parent": null },
    { "name": "Spine",         "parent": "Hips" },
    { "name": "Neck",          "parent": "Spine" },
    { "name": "Head",          "parent": "Neck" },
    { "name": "LeftShoulder",  "parent": "Spine" },
    { "name": "LeftUpperArm",  "parent": "LeftShoulder" },
    { "name": "LeftLowerArm",  "parent": "LeftUpperArm" },
    { "name": "LeftHand",      "parent": "LeftLowerArm" },
    { "name": "RightShoulder", "parent": "Spine" },
    { "name": "RightUpperArm", "parent": "RightShoulder" },
    { "name": "RightLowerArm", "parent": "RightUpperArm" },
    { "name": "RightHand",     "parent": "RightLowerArm" },
    { "name": "LeftUpperLeg",  "parent": "Hips" },
    { "name": "LeftLowerLeg",  "parent": "LeftUpperLeg" },
    { "name": "LeftFoot",      "parent": "LeftLowerLeg" },
    { "name": "RightUpperLeg", "parent": "Hips" },
    { "name": "RightLowerLeg", "parent": "RightUpperLeg" },
    { "name": "RightFoot",     "parent": "RightLowerLeg" }
  ]
}
```

---

## Backward compatibility

- Existing callers of `autorig_via_blender()` that unpack 2 values will break — update all call sites in the same PR
- GLB output is unchanged; FBX is additive
- `--no-fbx` restores old behaviour for callers that do not need FBX
