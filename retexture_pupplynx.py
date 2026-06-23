"""Re-bake texture on 1-pupplynx using front + back images."""
import sys, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT.parent / "modelGenerator" / "src"))

from PIL import Image as PILImage
from model_generator_cli.pipeline import (
    _white_bg_to_alpha, _crop_to_content, _sample_avg_color,
    _texture_bake_with_png, _scripts_dir,
)
from model_generator.blender_tools import autorig_via_blender

SCRIPTS = _scripts_dir()
NAME = "1-pupplynx"
INPUT     = ROOT / "input" / NAME
OUTPUT_3D  = ROOT / "output" / NAME / "3dmodel"
OUTPUT_TEX = ROOT / "output" / NAME / "textures"

# Use unrigged textured GLB — same +Z-facing geometry as Hunyuan3D output
source_glb = OUTPUT_3D / f"{NAME}_textured.glb"
if not source_glb.exists():
    sys.exit(f"Source GLB not found: {source_glb}")

def prep(path: Path) -> PILImage.Image:
    img = PILImage.open(path).convert("RGBA")
    return _crop_to_content(_white_bg_to_alpha(img))

image_paths = {
    "front": INPUT / "front_processed.png",
    "back":  INPUT / "back_processed.png",
}

tex_images = {}
for key, path in image_paths.items():
    if path.exists():
        tex_images[key] = prep(path)
        print(f"  Loaded {key}: {path.name}")

if not tex_images:
    sys.exit("No texture images found.")

base_color = _sample_avg_color(tex_images.get("front") or next(iter(tex_images.values())))
print(f"Base color: {base_color}")

print("Baking texture...")
baked_glb, baked_png, msg = _texture_bake_with_png(
    str(source_glb), tex_images, 2048,
    scripts_dir=SCRIPTS, base_color=base_color,
)
print(f"  {msg}")
if baked_glb is None:
    sys.exit("Texture bake failed.")

textured_out = OUTPUT_3D / f"{NAME}_textured.glb"
shutil.copy2(baked_glb, textured_out)
print(f"Saved textured GLB: {textured_out}")

if baked_png:
    OUTPUT_TEX.mkdir(parents=True, exist_ok=True)
    shutil.copy2(baked_png, OUTPUT_TEX / f"{NAME}.png")
    print(f"Saved albedo PNG: {OUTPUT_TEX / NAME}.png")

print("Re-rigging...")
rigged, rigged_fbx, manifest, rig_msg = autorig_via_blender(
    baked_glb, "auto", scripts_dir=SCRIPTS, export_fbx=True,
)
print(f"  {rig_msg}")
if rigged:
    shutil.copy2(rigged, OUTPUT_3D / f"{NAME}_textured_rigged.glb")
    print(f"Saved textured rigged GLB: {OUTPUT_3D / NAME}_textured_rigged.glb")
    if rigged_fbx:
        shutil.copy2(rigged_fbx, OUTPUT_3D / f"{NAME}_textured_rigged.fbx")
        print(f"Saved textured rigged FBX: {OUTPUT_3D / NAME}_textured_rigged.fbx")
else:
    print("Re-rig failed — textured GLB saved without rig.")

for p in [baked_glb, baked_png, rigged, rigged_fbx]:
    if p:
        try: Path(p).unlink(missing_ok=True)
        except: pass

print("Done.")
