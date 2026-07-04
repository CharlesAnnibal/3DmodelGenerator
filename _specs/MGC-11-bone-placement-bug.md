---
status: done
---

# MGC-11 — Bone Placement Bug (All Bones at Head)

## Bug report

On a my-creature generation, Unity's rig viewer showed all bones clustered at the head instead of distributed throughout the body. The `acceptance.json` for that run has a score of 0.773 and is truncated — the acceptance run crashed mid-check, which is consistent with a broken rig causing downstream code to fail.

Applying animation to a model with misplaced bones will not fix it. Unity's Humanoid retargeting only drives *rotations* around bone positions — if all pivots are at the head, the entire mesh will collapse or explode when animated.

## Root cause area

`autorig_via_blender()` in `modelGenerator/src/model_generator/blender_tools.py` calls a Blender script that places bones automatically based on the mesh shape. When the mesh silhouette doesn't match the expected body profile (likely my-creature's unusual body shape — stocky, wide, rock-studded), the bone placement heuristic fails to distribute bones along the body axis and defaults everything to a single origin near the head.

## Goal

1. Fix the bone placement heuristic so it distributes bones correctly for non-standard body shapes.
2. Add an acceptance check that catches this class of failure — bones must be spatially distributed across the mesh bounding box, not clustered at one point.

## Deliverables

1. **Bug fix** in the Blender auto-rig script: detect mesh extents and validate that the generated bone positions span at least 50% of the mesh height before export. If placement fails, abort with a clear error rather than silently exporting a broken rig.
2. **Acceptance check `R-xx` — Bone spatial distribution**: read the rig manifest (`{name}_rig_manifest.json`) and verify that bone positions are not all within a small radius. Threshold: bounding box of all bone positions must span ≥ 30% of the mesh height.
3. **Acceptance check `R-xx` — `acceptance.json` write guard**: ensure the acceptance run completes and writes a valid JSON file even when individual checks raise exceptions.

## Observed data

| Field | Value |
|---|---|
| Creature | `my-creature` |
| Acceptance score | 0.773 (FAIL) |
| `acceptance.json` | Truncated at check M-05 — run crashed |
| Symptom in Unity | All bones at head; mesh unanimatable |

## Acceptance criteria

- [ ] Generating my-creature produces bones distributed across the full body
- [ ] New acceptance check `R-xx` fails when all bones are within 10% of mesh height from each other
- [ ] New acceptance check passes on a correctly rigged humanoid and quadruped
- [ ] `acceptance.json` is always a valid complete JSON file, even when a check throws an exception
- [ ] The Blender script logs a clear error and exits non-zero if bone placement validation fails, so the pipeline warns instead of silently producing a broken FBX

## Constraints

- Fix must work for all three rig profiles: `humanoid`, `quadruped`, `serpentine`
- The rig manifest (`{name}_rig_manifest.json`) must include bone world positions (currently only names and parents are stored — positions need to be added)
