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

## Image input guidance

### Single image (recommended starting point)

Use one image named `front.png`. The pipeline uses `Hunyuan3D-2` (single-image model), which handles any angle.

**Best single-image choices, ranked:**

| View | Quality | Notes |
|---|---|---|
| 3/4 front-left or front-right | **Best** | Most depth information in one image — face + body side visible simultaneously. Hunyuan3D infers back geometry from the silhouette. |
| Front (strict 90°) | Good | Clean symmetry, but the model must guess depth entirely. Works well for stocky/round creatures. |
| Side (strict 90°) | Acceptable | Good depth cues, but face detail is lost. Use only if the creature's side profile is its defining feature. |

**How to use:**

```
input/
  my-creature/
    front.png    ← your single image (any angle)
```

A 3/4 illustration named `front.png` with no other views is the easiest path to a good generation.

---

### Three orthographic views (better geometry)

Use `front.png` + `back.png` + `side.png` (or `left.png`). The pipeline uses `Hunyuan3D-2mv` (multiview model), which resolves ambiguous geometry from multiple angles.

**Requirements:**
- Images must be true 90° orthographic views — straight front, straight back, strict side-on
- All three images should match in style, scale, and lighting
- A 3/4 or perspective image mixed into an orthographic set will distort the geometry

**What works:**

| Set | Result |
|---|---|
| `front` + `left` + `back` | Full geometry coverage — best multiview result |
| `front` + `right` + `back` | Same as above, mirrored |
| `front` + `left` | Good — back is inferred; avoids the front+back trap |

**What does not work:**

| Set | Problem |
|---|---|
| `front` + `back` only | **Rejected by the pipeline** — the model invents extra limbs to reconcile two flat views with no depth. Use front+left/right instead. |
| Orthographic + 3/4 mixed | Geometry distortion — the MV model expects all views at true 90° increments |

---

### Choosing between single-image and three-view

| Situation | Recommendation |
|---|---|
| You have a good 3/4 illustration | Single image (`front.png`) |
| You have a character sheet with precise 90° views | Three views |
| Your side view is actually 3/4 (not strict 90°) | Single image — don't mix it into a multiview set |
| Fast iteration / testing a new creature | Single image |
| Final production quality | Three views if you can produce true orthographics |

## Per-creature height via config.yaml

Each creature folder may contain a `config.yaml` file with a `height` key. This allows different heights in a single batch run without separate CLI invocations.

### Priority order

1. CLI flag (`--height`, `--small`, `--medium`, `--big`, `--huge`) — always wins
2. `config.yaml` `height` key in the creature folder
3. Default: `1.0 m` (`medium`)

### Format

```yaml
height: big       # preset name: small / medium / big / huge
# or
height: 1.8       # metres as a float
```

### Example batch

```
input/
  1-pupplynx/
    front.png
    config.yaml     ← height: small
  2-empalynx/
    front.png
    config.yaml     ← height: 1.8
  3-worcomb/
    front.png       ← no config.yaml, uses default (1.0 m)
```

```powershell
.\generator run    # each creature gets its own height
```

### Constraints

- Requires `pyyaml` (`pip install pyyaml`) — the pipeline exits with a clear error if missing
- Unknown keys in `config.yaml` are silently ignored (only `height` is read for now)
- Invalid height value exits with a readable error naming the bad value

## Acceptance criteria

- [ ] All flags in `_specs/general.md` flag reference table appear in README
- [ ] Size preset examples present (`--small`, `--big`, `--huge`, `--height 1.2`)
- [ ] Single-image mode note present (1 image → single-image model; 3/4 view works as `front.png`)
- [ ] front+back rejection noted with correct guidance
- [ ] Output structure matches actual output (GLB files, renders/, acceptance.json)
- [ ] FBX filenames match actual output (`{name}_rigged.fbx`, `{name}_textured_rigged.fbx`)
- [ ] `config.yaml` with `height: big` produces a 2.5 m model when no CLI height flag is set
- [ ] CLI `--small` overrides `config.yaml` height
- [ ] Missing `config.yaml` falls back to default 1.0 m
- [ ] Invalid height value in `config.yaml` exits with a clear error
- [ ] Missing `pyyaml` exits with an install hint
