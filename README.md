# modelGeneratorCLI

Turn creature reference art into game-ready 3D models, in batch, from the command line.

Point it at a folder of creatures — each just an image or two — and it runs the whole
image-to-asset pipeline: **shape generation** (Hunyuan3D-2) → **background removal** →
**mesh cleanup & leg-fix** → **texture bake** → **auto-rig** → **GLB + FBX** with a bone
manifest and validation renders. It was built to mass-produce creatures for a 3D game, but
it's a standalone tool — the models it produces drop straight into Unity, Blender, or any
glTF/FBX workflow.

It wraps the bundled **[`modelGenerator`](./modelGenerator)** core (which does the neural
generation and Blender work) with a batch runner, size/quality presets, and per-creature
config.

## What you get

For each input creature: a textured, rigged `*.glb` (the deliverable), a rigged `.fbx`
(e.g. for Mixamo), a bone/hierarchy manifest, a baked albedo texture, and six validation
renders. See [Output structure](#output-structure).

## Requirements

| Dependency | Version | Needed for |
|---|---|---|
| **Python** | 3.10+ | everything |
| **NVIDIA GPU + CUDA PyTorch** | CUDA 12.x, ~8 GB+ VRAM | shape generation & AI texture paint (CPU works but is slow) |
| **Blender** | 3.6+ | leg-fix, auto-rig, texture bake, renders |
| **Git** | any | cloning Hunyuan3D-2 |
| **Disk** | ~15 GB | model weights + Hunyuan3D-2 checkout |

> Hunyuan3D-2 is downloaded on first run from Hugging Face and needs a working GPU for
> reasonable speed. Low-VRAM cards can use `--preset "Hunyuan3D-2mini (low VRAM)"`.

### No GPU? (CPU-only mode)

You don't strictly need CUDA. The pipeline **auto-detects** the device — if no CUDA GPU is
available it falls back to CPU automatically, no flag required. Everything still works and
produces the same outputs.

> ⚠️ **CPU generation is very slow — budget roughly ~6 hours per creature.** Use it for the
> occasional one-off or on machines without a GPU; use CUDA for any real batch.

## Setup

The core lives in [`./modelGenerator`](./modelGenerator) and must be installed first
(it pulls in Hunyuan3D-2 and CUDA PyTorch). Full details in
[`modelGenerator/README.md`](./modelGenerator/README.md); the short version:

```powershell
# 1. core engine + its deps (from ./modelGenerator)
cd modelGenerator
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .

# 2. Hunyuan3D-2 (neural mesh model)
mkdir third_party; cd third_party
git clone https://github.com/Tencent-Hunyuan/Hunyuan3D-2.git
cd ..
pip install -r third_party/Hunyuan3D-2/requirements.txt
pip install -e third_party/Hunyuan3D-2
# CUDA PyTorch (match your CUDA version):
pip install -r requirements-torch-cuda.txt

# 3. this batch CLI (from the repo root)
cd ..
pip install -e .
```

Linux/macOS: same steps with a POSIX venv; use `./generate.sh` instead of `.\generator`.

## Input structure

Create a subfolder in `input/` for each creature. Place reference images named by view:

```
input/
  {name}/
    front.png       required — at least one view
    back.png        optional
    side.png        optional (aliased to left)
    left.png        optional
    right.png       optional
    config.yaml     optional — per-creature settings
```

`config.yaml` supports a `height` key (preset name or metres). CLI flags take precedence over config.

```yaml
height: big       # or small / medium / huge / 1.8
```

Supported formats: `.png`, `.jpg`, `.jpeg`, `.webp`

**1 image → single-image mode** (`Hunyuan3D-2`).  
**2+ images → multiview mode** (`Hunyuan3D-2mv`, better geometry).

> A 3/4 view works well as a single image — just name it `front.png` with no other views present.

> **Do not** use front+back as the only two views — the multiview model will invent extra limbs. Use front+left/right, or all four views.

## Image input guidance

### Single image (recommended starting point)

Use one image named `front.png`. The pipeline uses `Hunyuan3D-2` (single-image model), which handles any angle.

**Best single-image choices, ranked:**

| View | Quality | Notes |
|---|---|---|
| 3/4 front-left or front-right | **Best** | Most depth information in one image — face + body side visible simultaneously. Hunyuan3D infers back geometry from the silhouette. |
| Front (strict 90°) | Good | Clean symmetry, but the model must guess depth entirely. Works well for stocky/round creatures. |
| Side (strict 90°) | Acceptable | Good depth cues, but face detail is lost. Use only if the creature's side profile is its defining feature. |

```
input/
  my-creature/
    front.png    ← your single image (any angle)
```

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
| `front` + `back` only | **Rejected** — the model invents extra limbs. Use front+left/right instead. |
| Orthographic + 3/4 mixed | Geometry distortion — the MV model expects all views at true 90° increments |

### Choosing between single-image and three-view

| Situation | Recommendation |
|---|---|
| You have a good 3/4 illustration | Single image (`front.png`) |
| You have a character sheet with precise 90° views | Three views |
| Your side view is actually 3/4 (not strict 90°) | Single image — don't mix it into a multiview set |
| Fast iteration / testing a new creature | Single image |
| Final production quality | Three views if you can produce true orthographics |

## Output structure

```
output/
  {name}/
    3dmodel/
      {name}.glb                      untextured, rigged
      {name}_textured.glb             textured, not rigged
      {name}_textured_rigged.glb      textured + rigged (final deliverable)
      {name}_rigged.fbx               rigged untextured (for Mixamo upload)
      {name}_textured_rigged.fbx      rigged textured
      {name}_rig_manifest.json        bone names and hierarchy
    textures/
      {name}.png                      baked albedo
    renders/
      front.png  back.png  left.png  right.png  top.png  three_quarter.png
    acceptance.json                   quality check results
```

## Usage

There are three equivalent ways to invoke it:

- `.\generator run …` — PowerShell wrapper (Windows); also `.\generator clean` / `.\generator help`
- `./generate.sh run …` — POSIX wrapper (Linux/macOS)
- `model-factory run …` — the installed console script (any shell)
- `python -m model_generator_cli run …` — module form

Examples below use `.\generator`; substitute whichever you prefer.

### Run all creatures

```powershell
.\generator run
```

### Run a single creature

```powershell
.\generator run --creature my-creature
.\generator run --creature my-creature --height 1.2
```

### Size presets

```powershell
.\generator run --creature my-creature --small      # 0.3 m
.\generator run --creature my-creature              # 1.0 m (default)
.\generator run --creature my-creature --big        # 2.5 m
.\generator run --creature my-creature --huge       # 5.0 m
.\generator run --creature my-creature --height 0.4 # custom metres
```

### Quality presets

```powershell
.\generator run --preset "Hunyuan3D-2 (quality)"       # default, best quality
.\generator run --preset "Hunyuan3D-2 Turbo (faster)"  # faster, slightly lower quality
.\generator run --preset "Hunyuan3D-2mini (low VRAM)"  # for GPUs with less VRAM
```

### Texture control

```powershell
.\generator run --texture-size 1024   # lower res (faster bake)
.\generator run --texture-size 4096   # higher res
.\generator run --no-texture          # skip texture bake entirely
```

### Rig control

```powershell
.\generator run --rig-profile auto        # auto-detect (default)
.\generator run --rig-profile humanoid    # force humanoid
.\generator run --rig-profile quadruped   # force quadruped
.\generator run --rig-profile serpentine  # force serpentine
.\generator run --no-rig                  # skip rigging
.\generator run --no-fbx                  # skip FBX export (GLB only)
```

### Other flags

```powershell
.\generator run --no-rembg         # skip background removal
.\generator run --no-fix-legs      # skip merged-leg fix
.\generator run --no-acceptance    # skip acceptance checks
.\generator run --strict           # treat acceptance failure as a hard error
.\generator run --steps 10         # fewer diffusion steps (faster, lower quality)
.\generator run --octree-resolution 128  # lower mesh detail
.\generator run --seed 42          # custom seed for reproducibility
```

## Flag reference

| Flag | Default | Description |
|---|---|---|
| `--input-dir` | `./input` | Root directory with creature subfolders |
| `--output-dir` | `./output` | Root directory for generated output |
| `--preset` | `Hunyuan3D-2 (quality)` | Shape generation model preset |
| `--steps` | `40` | Diffusion sampling steps |
| `--octree-resolution` | `260` | Mesh extraction detail level |
| `--num-chunks` | `20000` | GPU memory chunking |
| `--seed` | `12345` | Reproducibility seed |
| `--texture-size` | `2048` | Albedo texture resolution (512/1024/2048/4096) |
| `--rig-profile` | `auto` | Rig body type (auto/humanoid/quadruped/serpentine) |
| `--height` | `medium` | Target height in metres or preset name |
| `--small` | | Shorthand for `--height small` (0.3 m) |
| `--medium` | | Shorthand for `--height medium` (1.0 m) |
| `--big` | | Shorthand for `--height big` (2.5 m) |
| `--huge` | | Shorthand for `--height huge` (5.0 m) |
| `--creature` | all | Process only this creature subfolder |
| `--no-rembg` | | Skip background removal |
| `--no-texture` | | Skip texture baking |
| `--no-fix-legs` | | Skip merged-leg fix |
| `--no-rig` | | Skip auto-rigging |
| `--no-fbx` | | Skip FBX export |
| `--no-acceptance` | | Skip acceptance checks |
| `--strict` | | Treat acceptance failures as hard errors |

## Pipeline steps

For each creature:

1. Load and detect view images
2. Remove background (rembg)
3. Shape generation (Hunyuan3D-2 or Hunyuan3D-2mv)
4. Scale normalization
5. Mesh decimation (target 100K faces)
6. Fix merged legs (Blender)
7. Auto-rig untextured model → `.glb` + `.fbx`
8. Texture bake (triplanar projection)
9. Auto-rig textured model → `_textured_rigged.glb` + `.fbx`
10. Acceptance checks

## Housekeeping

`.\generator clean` removes intermediate/debug artifacts from creature folders
(add `--creature <name>` to scope it, `--dry-run` to preview).

## Acknowledgements

This tool stands on:

- **[Hunyuan3D-2](https://github.com/Tencent-Hunyuan/Hunyuan3D-2)** — Tencent's image-to-3D
  neural model (shape + AI paint).
- **[Blender](https://www.blender.org/)** — mesh cleanup, auto-rig, texture bake, renders.
- **[rembg](https://github.com/danielgatis/rembg)** — background removal.
- **PyTorch**, and the wider glTF/FBX tooling ecosystem.

## License

This project's code is released under the **[MIT License](./LICENSE)** — free to use, modify,
and redistribute, provided the copyright notice is retained.

Note that the pipeline **downloads and runs Hunyuan3D-2**, which is distributed under
**Tencent's own model license / acceptable-use terms** — review and comply with those
before any commercial use. Generated assets are subject to the model's terms as well as the
license of your input images. This project is not affiliated with Tencent.
