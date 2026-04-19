## General Specs — Model Generator CLI

### Terminology

| Term | Definition |
|---|---|
| **Creature** | A game-ready 3D model generated from reference images. Each creature has a named subfolder under `input/`. |
| **View** | A reference image angle: `front`, `back`, `side`, `left`, `right`. |
| **Shape generation** | Diffusion-based 3D mesh creation via Hunyuan3D-2. |
| **Texture bake** | Projecting reference images onto the mesh and baking an albedo PNG via Blender Cycles. |
| **Base coat** | Fallback colour (average creature colour) applied to mesh surfaces not covered by any camera. |
| **Rig / Armature** | A skeleton with bones and vertex weights enabling animation. |
| **Acceptance** | Automated quality checks run after generation to catch silent failures. |
| **Profile** | Rig body type: `humanoid`, `quadruped`, or `serpentine`. |

---

### Conventions

- **1 unit = 1 metre** (glTF/GLB standard)
- **Z-up** in Blender and trimesh; Y-up in stored glTF (exporter rotates automatically)
- All models exported as **GLB** (binary glTF)
- Input images renamed with `_processed` suffix after successful generation
- Temp files are cleaned up in a `finally` block

---

### CLI Commands

#### Run the full pipeline

```
.\generator run [options]
python -m model_generator_cli [options]
```

#### Process a single creature

```
.\generator run --creature 3-worcomb
.\generator run --creature 2-empalynx --height 1.2
```

#### Size presets

```
.\generator run --creature 1-pupplynx --small     # 0.3 m
.\generator run --creature 1-pupplynx --medium    # 1.0 m (default)
.\generator run --creature 1-pupplynx --big       # 2.5 m
.\generator run --creature 1-pupplynx --huge      # 5.0 m
.\generator run --creature 1-pupplynx --height 0.4  # custom metres
```

#### Quality presets

```
.\generator run --preset "Hunyuan3D-2 (quality)"         # default, 20 steps
.\generator run --preset "Hunyuan3D-2 Turbo (faster)"    # 10 steps
.\generator run --preset "Hunyuan3D-2mini (low VRAM)"    # 15 steps
```

#### Texture control

```
.\generator run --texture-size 1024                # lower res (faster bake)
.\generator run --texture-size 4096                # higher res
.\generator run --no-texture                       # skip texture bake entirely
```

#### Rig control

```
.\generator run --rig-profile auto                 # auto-detect (default)
.\generator run --rig-profile humanoid             # force humanoid
.\generator run --rig-profile quadruped            # force quadruped
.\generator run --rig-profile serpentine           # force serpentine
.\generator run --no-rig                           # skip rigging
```

#### Other flags

```
.\generator run --no-rembg              # skip background removal
.\generator run --no-fix-legs           # skip leg fix
.\generator run --no-acceptance         # skip acceptance test
.\generator run --strict                # treat acceptance failure as hard error
.\generator run --steps 10              # fewer diffusion steps (faster, lower quality)
.\generator run --octree-resolution 128 # lower mesh detail
.\generator run --seed 42               # custom seed
```

---

### Full Flag Reference

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
| `--no-acceptance` | | Skip acceptance test checks |
| `--strict` | | Treat acceptance failures as hard errors |

---

### Input Structure

```
input/
  {name}/
    front.png          (required — at least one view)
    back.png           (optional)
    side.png           (optional, aliased to left)
    left.png           (optional)
    right.png          (optional)
```

Supported formats: `.png`, `.jpg`, `.jpeg`, `.webp`

---

### Output Structure

```
output/
  {name}/
    3dmodel/
      {name}.glb                    ← untextured, rigged
      {name}_textured.glb           ← textured, not rigged
      {name}_textured_rigged.glb    ← textured + rigged (final deliverable)
    textures/
      {name}.png                    ← baked albedo
    renders/
      front.png, back.png, left.png, right.png, top.png, three_quarter.png
    acceptance.json                 ← quality check results
```

---

### Environment Requirements

| Dependency | Required | Notes |
|---|---|---|
| Python 3.10+ | yes | |
| PyTorch | yes | CPU or CUDA build |
| Hunyuan3D-2 (hy3dgen) | yes | Shape generation |
| Blender | yes | Texture bake, leg fix, rigging, renders |
| trimesh | yes | Mesh I/O and decimation |
| Pillow | yes | Image processing |
| tqdm | yes | Progress bars |
| numpy | yes | Numeric operations |
| rembg | optional | Background removal (skip with `--no-rembg`) |
| pygltflib | optional | Full rig acceptance checks |
