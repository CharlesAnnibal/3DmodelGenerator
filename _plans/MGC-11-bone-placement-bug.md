---
status: done
---

# MGC-11 — Bone Placement Bug

## Root cause analysis

`_write_rig_manifest()` in `autorig_humanoid_blender.py` stores only bone names and
parents — no positions. This means the acceptance suite has no way to detect bones
clustered at a single point. The existing G-05 check ("root bone within mesh bounds")
only validates the root bone's Y coordinate, not the full skeleton distribution.

The bone placement logic itself (`_bounds_world` + `_detect_limb_columns`) looks
correct for standard shapes. The likely failure mode for worcomb: `_detect_limb_columns`
returned < 2 clusters (rocky armor obscures the limb silhouette at the z_cutoff), so
both legs were placed at the same cx/cy fallback — and the auto-profile detected
"humanoid" instead of "quadruped", compounding the misplacement.

## Changes

### `modelGenerator/scripts/autorig_humanoid_blender.py`

1. `_write_rig_manifest()` — add `"head": [x, y, z]` to each bone entry using
   `b.head_local` (armature-local coords = world coords since armature is at origin).
2. After building the armature, validate that bone head Z positions span ≥ 30% of
   mesh height. If not, print a `[autorig] WARNING` (don't abort — partial rig is
   better than no rig).

### `modelGeneratorCLI/src/model_generator_cli/acceptance.py`

1. New check **G-06 "Bone spatial distribution"** in `_check_rigging()`:
   - Read `{name}_rig_manifest.json`
   - Extract `bones[].head` positions
   - Compute Z range of all bone heads
   - Fail (HIGH) if Z range < 15% of mesh height (bones clustered)
   - Skip gracefully if manifest missing or has no positions (old format)

2. Atomic JSON write in `run_acceptance()`: write to a temp file then `rename()` so a
   mid-write crash never leaves a truncated acceptance.json.

## Files changed

| File | Change |
|---|---|
| `modelGenerator/scripts/autorig_humanoid_blender.py` | Add bone positions to manifest; add post-build distribution warning |
| `src/model_generator_cli/acceptance.py` | Add G-06 check; atomic JSON write |
| `_specs/index.md` | Status updated |
