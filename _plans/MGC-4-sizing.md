# Plan: MGC-4 — Scale Normalization / Sizing

## Affected files

| File | Change |
|---|---|
| `src/model_generator_cli/__main__.py` | add `--height`, `--small`, `--medium`, `--big`, `--huge` flags and `_resolve_target_height` |
| `src/model_generator_cli/pipeline.py` | add scale normalization step 4b after raw GLB export |
| `_specs/MGC-4-sizing.md` | document size presets and conventions |

## Implementation steps

- [x] Step 1 — Add `_HEIGHT_PRESETS` dict and `_resolve_target_height()` to `__main__.py`
- [x] Step 2 — Add `--height` flag (accepts decimal or preset name) and `--small/--medium/--big/--huge` shorthand flags to argparse
- [x] Step 3 — Pass `target_height` to `process_creature()` from `_resolve_target_height(args)`
- [x] Step 4 — In `pipeline.py` step 4b: load raw mesh via trimesh, measure Z-axis bbox, compute `scale_factor = target / bbox_Z`, apply uniform scale, export new `current_glb`
- [x] Step 5 — Add acceptance check M-09 (height within +/-10% of target) and M-10 (not flat/needle) to `acceptance.py`

## Scale normalization logic (step 4b in pipeline)

```python
import trimesh
import numpy as np

mesh = trimesh.load(current_glb, force="mesh", process=False)
verts = np.asarray(mesh.vertices)
bbox_z = float(verts[:, 2].max() - verts[:, 2].min())
if bbox_z > 1e-6:
    scale = target_height / bbox_z
    mesh.apply_scale(scale)
    mesh.export(scaled_glb_path)
    current_glb = scaled_glb_path
```

## Size presets

| Flag | Preset | Target height | Real-world reference |
|---|---|---|---|
| `--small` | `small` | 0.30 m | Cat / small animal |
| `--medium` | `medium` | 1.00 m | Medium creature (default) |
| `--big` | `big` | 2.50 m | Bear / large animal |
| `--huge` | `huge` | 5.00 m | Boss / giant creature |

`--height` takes precedence over preset flags if both are given.

## Acceptance checks

| ID | Check | Pass condition | Severity |
|---|---|---|---|
| M-09 | Height within target band | `abs(bbox_Z - target) / target <= 0.10` | HIGH |
| M-10 | Not flat/needle | `bbox_Z / max(bbox_X, bbox_Y)` in [0.1, 20] | MEDIUM |
