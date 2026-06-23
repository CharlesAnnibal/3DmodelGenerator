"""Texture-bake a creature from its concept images, then rig it.

For creatures that were never textured (only a raw mesh GLB) or need a fresh
texture pass. Bakes the per-creature concept views (front/back/side from
models/{creature}/images/) onto the mesh, saves *_textured.glb, then runs the
auto-rig with the profile from config.yaml (rig_profile), writing
*_textured_rigged.glb / .fbx / *_rig_manifest.json.

Usage:
  python scripts/retexture_and_rig.py --creature 16-venopolis [--creature ...] [--no-write]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "modelGenerator" / "src"))

from PIL import Image as PILImage  # noqa: E402
from model_generator_cli.pipeline import (  # noqa: E402
    _white_bg_to_alpha, _crop_to_content, _sample_avg_color,
    _texture_bake_with_png, _scripts_dir,
)
from model_generator.blender_tools import autorig_via_blender  # noqa: E402

SCRIPTS = _scripts_dir()


def _read_config(folder: Path) -> dict:
    for path in (folder / "images" / "config.yaml", folder / "config.yaml"):
        if not path.is_file():
            continue
        try:
            import yaml
        except ImportError:
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    return {}


def _first(paths):
    found = sorted(paths)
    return found[0] if found else None


def _prep(path: Path) -> PILImage.Image:
    return _crop_to_content(_white_bg_to_alpha(PILImage.open(path).convert("RGBA")))


def _source_mesh(model_dir: Path):
    """Prefer an existing un-rigged textured GLB; else the raw base mesh
    (a *.glb that is neither _rigged nor _textured)."""
    tex = _first(model_dir.glob("*_textured.glb"))
    if tex:
        return tex
    for p in sorted(model_dir.glob("*.glb")):
        n = p.name.lower()
        if "_rigged" in n or "_textured" in n or n.endswith(".bak"):
            continue
        return p
    return None


def _stem(glb: Path) -> str:
    n = glb.name
    for suf in ("_textured_rigged.glb", "_textured.glb", ".glb"):
        if n.endswith(suf):
            return n[: -len(suf)]
    return glb.stem


def retexture_creature(folder: Path, *, write: bool) -> bool:
    model_dir = folder / "3dmodel"
    img_dir = folder / "images"
    source = _source_mesh(model_dir)
    if source is None:
        print(f"SKIP {folder.name}: no source mesh GLB in {model_dir}")
        return False

    # Concept views: prefer the *_processed.png (white bg removed); fall back to raw.
    views = {}
    for key in ("front", "back", "side"):
        p = _first(img_dir.glob(f"{key}_processed.png")) or _first(img_dir.glob(f"{key}.png"))
        if p:
            views[key] = p
    if not views:
        print(f"SKIP {folder.name}: no concept images in {img_dir}")
        return False

    cfg = _read_config(folder)
    profile = str(cfg.get("rig_profile") or "auto")
    stem = _stem(source)
    print(f"{'' if write else 'DRY '}TEXTURE+RIG {folder.name}: src={source.name} profile={profile} views={list(views)}")
    if not write:
        return True

    images = {k: _prep(v) for k, v in views.items()}
    base_color = _sample_avg_color(images.get("front") or next(iter(images.values())))

    baked_glb, baked_png, msg = _texture_bake_with_png(
        str(source), images, 2048, scripts_dir=SCRIPTS, base_color=base_color,
    )
    print(f"  bake: {msg}")
    if baked_glb is None:
        print(f"FAIL {folder.name}: texture bake failed")
        return False

    out_textured = model_dir / f"{stem}_textured.glb"
    shutil.copy2(baked_glb, out_textured)

    rigged, rigged_fbx, manifest, rig_msg = autorig_via_blender(
        baked_glb, profile, scripts_dir=ROOT / "modelGenerator" / "scripts", export_fbx=True,
    )
    print(f"  rig: {rig_msg}")
    if rigged:
        shutil.copy2(rigged, model_dir / f"{stem}_textured_rigged.glb")
        if rigged_fbx:
            shutil.copy2(rigged_fbx, model_dir / f"{stem}_textured_rigged.fbx")
        if manifest:
            shutil.copy2(manifest, model_dir / f"{stem}_rig_manifest.json")
    else:
        print(f"  WARN {folder.name}: textured saved, rig failed")

    for tmp in (baked_glb, baked_png, rigged, rigged_fbx, manifest):
        if tmp:
            Path(tmp).unlink(missing_ok=True)

    print(f"OK {folder.name}: wrote {out_textured.name} (+ rigged)")
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models-dir", type=Path, default=ROOT / "models")
    ap.add_argument("--creature", action="append", required=True, help="Folder name; repeatable.")
    ap.add_argument("--no-write", action="store_true", help="Dry run.")
    args = ap.parse_args()

    ok = fail = 0
    for name in args.creature:
        folder = args.models_dir / name
        if not folder.is_dir():
            print(f"SKIP {name}: folder not found")
            fail += 1
            continue
        if retexture_creature(folder, write=not args.no_write):
            ok += 1
        else:
            fail += 1
    print(f"Done: {ok} ok, {fail} failed/skipped")


if __name__ == "__main__":
    main()
