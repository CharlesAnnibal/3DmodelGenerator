# modelGenerator

**100% offline** local app: **image(s)** → **GLB** for **Unity** (see [`docs/unity_import_and_rigging.md`](docs/unity_import_and_rigging.md)).

## What it does today

| Input | Result |
|--------|--------|
| **Front + side** (+ optional **top / back / bottom**) | **Visual hull** — voxel spacing matches **front width / height** and **side depth** so **length** is not flattened. **Top**/**bottom** auto-pick **original vs transposed** alignment when that tightens the hull. **Luminance depth** adds face relief (**~0.15–0.25**). Env: ``MODEL_GENERATOR_NO_BBOX_CROP=1``, ``MODEL_GENERATOR_NO_AUTO_PLAN_SWAP=1``, ``MODEL_GENERATOR_TOP_BOTTOM_ERODE=1``, ``MODEL_GENERATOR_VOXEL_OPEN=1``. |
| **Front only** | Volumetric **silhouette** (front/back/side walls) + optional **vertical asymmetry** and **luminance depth** (weak heuristics, not full AI). |
| **`reference/reference.glb`** on disk | Copies that mesh (scaled). Images ignored. Omit this file for generation from images. |

**Output:** **GLB**. If **Blender** is installed, meshes are **re-exported** through Blender’s glTF exporter (same as `scripts/reexport_glb_blender.py`). Set **`MODEL_GENERATOR_NO_BLENDER_REEXPORT=1`** to skip. **`BLENDER_EXE`** overrides the Blender path.

**Unity import:** exports apply **scale (1, −1, 1)** by default to fix meshes that look **Y-inverted** in Unity (without the old **180° X** rotation that also flipped **Z**). For **180° about Y** instead, set **`MODEL_GENERATOR_UNITY_YAW_180=1`**. To disable, set **`MODEL_GENERATOR_NO_UNITY_ROTATE=1`**. Optional **`MODEL_GENERATOR_SMOOTH_ITER`** (default **6**, **`0`** = off) runs mild Laplacian smoothing before export to soften blocky hulls.

## Good examples folder

Put trusted **inputs** and **gold** meshes under [`assets/samples/good/`](assets/samples/good/README.md) (`images/`, `models/`). The app does not read them automatically; they are for your reference.

## Layout

| Path | Purpose |
|------|---------|
| `src/model_generator/` | App, mesh build, GLB export |
| `assets/samples/good/` | Your “known good” images / models (optional) |
| `reference/` | Optional `reference.glb` to **copy** (see [`reference/README.md`](reference/README.md)) |
| `output/` | Generated files (gitignored) |
| `weights/` | Future ML checkpoints (gitignored) |
| `docs/` | Unity import, rigging |

## Setup (Windows)

```powershell
cd modelGenerator
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

## Run the UI

```powershell
python -m model_generator
```

Upload **front** (required) and optionally **side** for best shape. Adjust sliders, **Generate GLB**, download. The page header shows **engine version** and Python version — after updating code, run **`pip install -e .`** (if needed) and **restart** the app so you are not on a stale process.

## Roadmap

1. Plug in a local **image-to-3D** model (PyTorch, etc.) in place of heuristics; keep `export_glb.py` / `pipeline.py`.
2. **Rig** in Blender → Unity **Animator**.
3. **Texture** in Blender/Substance → Unity materials.

## CLI smoke test

```powershell
python -c "from pathlib import Path; from PIL import Image; from model_generator.pipeline import generate_glb_from_image; p=Path('output/test.glb'); im=Image.new('RGB',(64,64),(200,100,50)); generate_glb_from_image(im, p); print(p)"
```

Run from `modelGenerator` with the venv activated after `pip install -e .`.
