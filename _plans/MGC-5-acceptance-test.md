# Plan: MGC-5 — Acceptance Test Suite

Automated quality gate that runs after each creature generation. Catches
silent failures (black textures, missing rigs, degenerate meshes) without
human review.

## Affected files

| File | Change |
|---|---|
| `src/model_generator_cli/acceptance.py` | create — all assertion logic (file, mesh, texture, rig, render checks) |
| `scripts/render_views_blender.py` | create — headless Blender EEVEE render at 6 camera positions |
| `src/model_generator_cli/pipeline.py` | add acceptance call at step 10 |
| `src/model_generator_cli/__main__.py` | add `--no-acceptance`, `--strict` flags |
| `_specs/MGC-5-acceptance-test.md` | full check specification |

## Implementation steps

- [x] Step 1 — Write `render_views_blender.py`: import model, 6 orthographic cameras, EEVEE render, transparent PNG output
- [x] Step 2 — Write `acceptance.py`: file checks (F-01 to F-06)
- [x] Step 3 — Write `acceptance.py`: mesh quality checks (M-01 to M-10) via trimesh
- [x] Step 4 — Write `acceptance.py`: texture/albedo checks (T-01 to T-05) via PIL
- [x] Step 5 — Write `acceptance.py`: rigging checks (G-01 to G-05) via pygltflib
- [x] Step 6 — Write `acceptance.py`: render-based checks (R-01 to R-08) with histogram comparison
- [x] Step 7 — Implement scoring: severity weights (CRITICAL=3, HIGH=2, MEDIUM=1), pass criteria
- [x] Step 8 — Wire into pipeline step 10, write `acceptance.json`, add `--no-acceptance` and `--strict` flags

---

## Architecture

```
pipeline.py step 10
    │
    ├─ File checks (F-01 to F-06)
    ├─ Mesh checks (M-01 to M-10)    ← via trimesh
    ├─ Texture checks (T-01 to T-05) ← via PIL
    ├─ Rigging checks (G-01 to G-05) ← via pygltflib
    ├─ Render views (Blender EEVEE)
    └─ Render checks (R-01 to R-08)  ← histogram comparison
    │
    ▼
  acceptance.json + console summary
```

---

## Check Categories

### File Checks (F-xx)

| ID | Check | Pass | Severity |
|----|-------|------|----------|
| F-01 | `_textured_rigged.glb` exists | present | CRITICAL |
| F-02 | `_textured_rigged.glb` not empty | > 500 KB | CRITICAL |
| F-03 | `_textured.glb` exists | present | HIGH |
| F-04 | albedo PNG exists | present | HIGH |
| F-05 | albedo PNG not empty | > 10 KB | HIGH |
| F-06 | GLB loads without error | trimesh OK | CRITICAL |

### Mesh Checks (M-xx)

| ID | Check | Pass | Severity |
|----|-------|------|----------|
| M-01 | Vertex count | 5K-500K | HIGH |
| M-02 | Face count | 3K-1M | HIGH |
| M-03 | No NaN/Inf vertices | all finite | CRITICAL |
| M-04 | Bbox not degenerate | all dims > 0.01 | CRITICAL |
| M-05 | Reasonable aspect ratio | H/max(W,D) in [0.2, 10] | MEDIUM |
| M-06 | Connected components | 1-5 | MEDIUM |
| M-07 | No zero-area faces | 0 | MEDIUM |
| M-08 | Vertex normals | unit-length | HIGH |
| M-09 | Height within target | +/-10% of --height | HIGH |
| M-10 | Not flat/needle | Z/max(X,Y) in [0.1, 20] | MEDIUM |

### Texture Checks (T-xx)

| ID | Check | Pass | Severity |
|----|-------|------|----------|
| T-01 | Not black | > 15% non-black pixels | CRITICAL |
| T-02 | Not neutral grey | < 80% near (180,180,180) | HIGH |
| T-03 | Colour variance | min channel std > 8 | HIGH |
| T-04 | No dominant hue | no channel > 60% | MEDIUM |
| T-05 | Not transparent | alpha mean > 0.3 | MEDIUM |

### Rigging Checks (G-xx)

| ID | Check | Pass | Severity |
|----|-------|------|----------|
| G-01 | Skeleton exists | >= 1 skin | CRITICAL |
| G-02 | Bone count | >= 8 | HIGH |
| G-03 | No zero-weight verts | all sums > 0 | HIGH |
| G-04 | Weight normalization | sums in [0.95, 1.05] | MEDIUM |
| G-05 | Root bone position | within mesh bounds | MEDIUM |

### Render Checks (R-xx)

| ID | View | Check | Pass | Severity |
|----|------|-------|------|----------|
| R-01 | front | Mesh visible | > 20% non-transparent | CRITICAL |
| R-02 | front | Not black silhouette | > 10% non-black fg | HIGH |
| R-03 | front | Histogram vs reference | cosine sim >= 0.65 | HIGH |
| R-04 | back | Mesh visible | > 15% non-transparent | HIGH |
| R-05 | back | Histogram vs reference | cosine sim >= 0.60 | MEDIUM |
| R-06 | left | Mesh visible | > 10% non-transparent | HIGH |
| R-07 | top | Limb separation | bbox W/H < 3 | MEDIUM |
| R-08 | 3/4 | Not black | > 20% non-black fg | HIGH |

---

## Scoring

- Weights: CRITICAL=3, HIGH=2, MEDIUM=1
- Score = sum(passed weights) / sum(all weights)
- **PASS** = zero CRITICAL failures AND <= 2 HIGH failures

---

## Render Setup

Camera: orthographic, fits mesh bounding box x 1.2 scale.
Engine: EEVEE, 16 samples, transparent background, 256x256.

| View | Azimuth | Elevation | Distance |
|------|---------|-----------|----------|
| front | 0 | 0 | 1.8x diagonal |
| back | 180 | 0 | 1.8x |
| left | 90 | 0 | 1.8x |
| right | 270 | 0 | 1.8x |
| top | 0 | 90 | 1.8x |
| 3/4 front | 45 | 30 | 2.0x |

---

## Output

```
output/{name}/
  acceptance.json      ← full results
  renders/
    front.png
    back.png
    left.png
    right.png
    top.png
    three_quarter.png
```

---

## CLI Integration

- Runs by default at end of pipeline
- `--no-acceptance` skips it
- `--strict` makes acceptance failure a hard error (creature counts as
  failed in batch summary)

---

## Key Files

| File | Role |
|------|------|
| `src/model_generator_cli/acceptance.py` | All assertion logic |
| `scripts/render_views_blender.py` | Headless Blender render script |
| `_specs/acceptance-test.md` | Full specification |
