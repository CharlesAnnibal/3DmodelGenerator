"""Re-bake texture on 9-mantorment using three_quarter diagonal projection."""
import sys, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT.parent / "modelGenerator" / "src"))

from PIL import Image as PILImage
from model_generator_cli.pipeline import (
    _white_bg_to_alpha, _crop_to_content,
    _texture_bake_with_png, _scripts_dir,
)
from model_generator.blender_tools import autorig_via_blender

SCRIPTS = _scripts_dir()
NAME = "25-mantorment"
IMAGES  = ROOT / "models" / NAME / "images"
OUT_3D  = ROOT / "models" / NAME / "3dmodel"
OUT_TEX = ROOT / "models" / NAME / "textures"

source_glb = OUT_3D / f"{NAME}.glb"
if not source_glb.exists():
    sys.exit(f"Source GLB not found: {source_glb}")

def prep(path: Path) -> PILImage.Image:
    img = PILImage.open(path).convert("RGBA")
    return _crop_to_content(_white_bg_to_alpha(img))

tq_path = IMAGES / "three_quarter_processed.png"
if not tq_path.exists():
    sys.exit(f"three_quarter image not found: {tq_path}")

tex_images = {"three_quarter": prep(tq_path)}
print(f"  Loaded three_quarter: {tq_path.name}")

from model_generator_cli.pipeline import _sample_avg_color
base_color = _sample_avg_color(tex_images["three_quarter"])
print(f"Base color: {base_color}")

print("Baking texture...")
baked_glb, baked_png, msg = _texture_bake_with_png(
    str(source_glb), tex_images, 2048,
    scripts_dir=SCRIPTS, base_color=base_color,
)
print(f"  {msg}")
if baked_glb is None:
    sys.exit("Texture bake failed.")

OUT_TEX.mkdir(parents=True, exist_ok=True)
shutil.copy2(baked_glb, OUT_3D / f"{NAME}_textured.glb")
print(f"Saved textured GLB: {OUT_3D / f'{NAME}_textured.glb'}")
if baked_png:
    shutil.copy2(baked_png, OUT_TEX / f"{NAME}.png")
    print(f"Saved albedo PNG: {OUT_TEX / f'{NAME}.png'}")

print("Re-rigging...")
rigged, rigged_fbx, manifest, rig_msg = autorig_via_blender(
    baked_glb, "auto", scripts_dir=SCRIPTS, export_fbx=True,
)
print(f"  {rig_msg}")
if rigged:
    shutil.copy2(rigged, OUT_3D / f"{NAME}_textured_rigged.glb")
    print(f"Saved textured rigged GLB")
    if rigged_fbx:
        shutil.copy2(rigged_fbx, OUT_3D / f"{NAME}_textured_rigged.fbx")
        print(f"Saved textured rigged FBX")
else:
    print("Re-rig failed — textured GLB saved without rig.")

for p in [baked_glb, baked_png, rigged, rigged_fbx]:
    if p:
        try: Path(p).unlink(missing_ok=True)
        except: pass

print("Done.")
