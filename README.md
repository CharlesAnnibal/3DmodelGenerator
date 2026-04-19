# modelGeneratorCLI

Batch CLI pipeline for Hunyuan3D-2 creature model generation. Processes creature folders from `input/` through shape generation, texture baking, leg fixing, and auto-rigging — outputting GLB and FBX models with baked textures.

## Prerequisites

- **modelGenerator** sibling project installed (`pip install -e .` from `../modelGenerator`)
- **Hunyuan3D-2** cloned into `../modelGenerator/third_party/Hunyuan3D-2`
- **Blender 3.6+** installed (for texture baking, leg fix, auto-rig, and renders)
- **Python 3.10+**

## Setup

```powershell
cd modelGeneratorCLI
pip install -e .
```

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
```

Supported formats: `.png`, `.jpg`, `.jpeg`, `.webp`

**1 image → single-image mode** (`Hunyuan3D-2`).  
**2+ images → multiview mode** (`Hunyuan3D-2mv`, better geometry).

> A 3/4 view works well as a single image — just name it `front.png` with no other views present.

> **Do not** use front+back as the only two views — the multiview model will invent extra limbs. Use front+left/right, or all four views.

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

### Run all creatures

```powershell
.\generator run
# or
python -m model_generator_cli
```

### Run a single creature

```powershell
.\generator run --creature 3-worcomb
.\generator run --creature 2-empalynx --height 1.2
```

### Size presets

```powershell
.\generator run --creature 1-pupplynx --small      # 0.3 m
.\generator run --creature 1-pupplynx              # 1.0 m (default)
.\generator run --creature 1-pupplynx --big        # 2.5 m
.\generator run --creature 1-pupplynx --huge       # 5.0 m
.\generator run --creature 1-pupplynx --height 0.4 # custom metres
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
