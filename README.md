# modelGeneratorCLI

Batch CLI pipeline for Hunyuan3D-2 creature model generation. Processes creature folders from `input/` through shape generation, texture baking, leg fixing, and auto-rigging — outputting FBX models and PNG textures.

## Prerequisites

- **modelGenerator** sibling project installed (`pip install -e .` from `../modelGenerator`)
- **Hunyuan3D-2** cloned into `../modelGenerator/third_party/Hunyuan3D-2`
- **Blender 3.6+** installed (for texture baking, leg fix, and auto-rig)
- **Python 3.10+**

## Setup

```powershell
cd modelGeneratorCLI
pip install -e .
```

## Usage

### Prepare input

Create a subfolder in `input/` for each creature. Place reference images named by view:

```
input/
  pupplynx/
    front.png
    back.png
    side.png
  dragoncat/
    front.jpg
    side.jpg
```

Supported view names: `front`, `back`, `side`, `left`, `right`  
Supported formats: `.png`, `.jpg`, `.jpeg`, `.webp`

- 1 image → single-image mode
- 2+ images → multiview mode (better geometry)

### Run

```powershell
model-factory
# or
python -m model_generator_cli
```

### Output

```
output/
  pupplynx/
    3dmodel/
      pupplynx.fbx                (rigged, untextured)
      pupplynx_texturized.fbx     (rigged, textured)
    textures/
      pupplynx.png                (albedo texture)
```

### Options

List all CLI options with defaults:

- `--input-dir` (`./input`)
- `--output-dir` (`./output`)
- `--preset` (`Hunyuan3D-2 (quality)`)
- `--steps` (`40`)
- `--octree-resolution` (`260`)
- `--num-chunks` (`20000`)
- `--seed` (`12345`)
- `--texture-size` (`2048`)
- `--rig-profile` (`auto`)
- `--no-rembg`, `--no-texture`, `--no-fix-legs`, `--no-rig`
- `--creature NAME` (process only one)

Use `model-factory --help` for choices (presets, rig profiles) and full help text.

### Pipeline steps

For each creature:

1. Load and detect view images
2. Remove background (rembg)
3. Shape generation (Hunyuan3D-2)
4. Fix merged legs (Blender)
5. Auto-rig untextured → `name.fbx`
6. Texture bake (Blender multi-view projection)
7. Auto-rig textured → `name_texturized.fbx`

### Error handling

- Empty folders: warning printed, creature skipped
- Errors in any step: error printed, creature skipped, next creature processed
- Progress bar shows overall progress across all creatures
