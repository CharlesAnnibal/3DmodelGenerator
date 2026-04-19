---
status: done
---

# MGC-9 — README Update

## Problem

The README is significantly behind the actual CLI. Missing flags, wrong output structure, and no guidance on single-image mode mean users have to read `_specs/general.md` or the source to understand what the tool can do.

## Goal

Bring `README.md` up to date with the current pipeline so it is the single reference a new user needs.

## Gaps to close

| Area | Gap |
|---|---|
| Size flags | `--small`, `--medium`, `--big`, `--huge`, `--height` not documented |
| Flags | `--no-fbx`, `--no-acceptance`, `--strict`, `--steps`, `--octree-resolution`, `--seed` missing |
| Preset examples | No examples of `--preset` or `--rig-profile` usage |
| Texture size | `--texture-size` listed but no examples |
| Single-image note | No mention that a single `front.png` triggers single-image mode (and that a 3/4 image works as `front.png`) |
| front+back warning | No mention that front+back only is rejected; user needs front+left/right or all four |
| Output structure | Missing `.glb` files, `renders/`, `acceptance.json`; FBX names are wrong |
| Flag reference table | Options section is a bullet list with no descriptions |

## Deliverables

1. `README.md` rewritten to match `_specs/general.md` as the authoritative reference.

## Acceptance criteria

- [ ] All flags in `_specs/general.md` flag reference table appear in README
- [ ] Size preset examples present (`--small`, `--big`, `--huge`, `--height 1.2`)
- [ ] Single-image mode note present (1 image → single-image model; 3/4 view works as `front.png`)
- [ ] front+back rejection noted with correct guidance
- [ ] Output structure matches actual output (GLB files, renders/, acceptance.json)
- [ ] FBX filenames match actual output (`{name}_rigged.fbx`, `{name}_textured_rigged.fbx`)
