"""Isolated texture-bake smoke test.

Runs ONLY the Blender multi-view texture bake against an existing GLB and a
folder of reference images.  Intended for fast iteration on
``scripts/texture_bake_blender.py`` (shader node tree, visibility threshold,
etc.) without paying the 30-minute cost of a full Hunyuan3D regeneration.

Usage
-----
  py -3 test_texture_bake.py
  py -3 test_texture_bake.py --name 2-empalynx
  py -3 test_texture_bake.py --glb output/2-empalynx/3dmodel/2-empalynx.glb \\
                             --input-dir input/2-empalynx
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# sys.path bootstrap (same layout as test_pipeline.py)
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent
_CLI_SRC = _ROOT / "src"
_MG_SRC = _ROOT.parent / "modelGenerator" / "src"
_HUNYUAN_SRC = _ROOT.parent / "modelGenerator" / "third_party" / "Hunyuan3D-2"
for _p in (_CLI_SRC, _MG_SRC, _HUNYUAN_SRC):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

_SCRIPTS = _ROOT.parent / "modelGenerator" / "scripts"


# ---------------------------------------------------------------------------
# Image discovery
# ---------------------------------------------------------------------------

_VIEW_KEYS = ("front", "back", "left", "right", "side")
_EXTS = (".webp", ".png", ".jpg", ".jpeg")


def _find_view(input_dir: Path, view: str) -> Path | None:
    """Locate a reference image for *view* in *input_dir*.

    Tries ``{view}_processed.ext``, then ``{view}.ext``, for each extension.
    """
    for ext in _EXTS:
        p = input_dir / f"{view}_processed{ext}"
        if p.is_file():
            return p
    for ext in _EXTS:
        p = input_dir / f"{view}{ext}"
        if p.is_file():
            return p
    return None


def _load_reference_images(input_dir: Path):
    from PIL import Image as PILImage

    raw: dict[str, "PILImage.Image"] = {}
    for key in _VIEW_KEYS:
        path = _find_view(input_dir, key)
        if path is not None:
            raw[key] = PILImage.open(path).convert("RGBA")
            print(f"  loaded {key:<6} <- {path.name}")

    if "side" in raw and "left" not in raw:
        raw["left"] = raw.pop("side")

    return raw


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _resolve_glb(name: str, explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            sys.exit(f"GLB not found: {p}")
        return p
    base = _ROOT / "output" / name / "3dmodel"
    # Prefer the post-bake pre-rig mesh: it has no armature, so Blender bake
    # is ~10x faster than on {name}.glb (which is auto-rigged and has a skinned
    # mesh).  Rebaking overwrites the existing texture, which is fine for
    # iteration.
    for fname in (f"{name}_textured.glb", f"{name}.glb", f"{name}_textured_rigged.glb"):
        p = base / fname
        if p.is_file():
            return p
    sys.exit(f"No GLB found under {base} (tried _textured, {name}.glb, _textured_rigged)")


def run(args: argparse.Namespace) -> None:
    from model_generator_cli.pipeline import (
        _crop_to_content,
        _sample_avg_color,
        _texture_bake_with_png,
        _white_bg_to_alpha,
    )

    name = args.name
    glb_path = _resolve_glb(name, args.glb)
    input_dir = Path(args.input_dir) if args.input_dir else _ROOT / "input" / name
    if not input_dir.is_dir():
        sys.exit(f"Input directory not found: {input_dir}")

    print(f"[test_texture_bake] name       = {name}")
    print(f"[test_texture_bake] source GLB = {glb_path}")
    print(f"[test_texture_bake] input dir  = {input_dir}")
    print(f"[test_texture_bake] tex size   = {args.texture_size}")

    print("\n[step] Loading reference images")
    raw_views = _load_reference_images(input_dir)
    if not raw_views:
        sys.exit(f"No reference images found in {input_dir}")

    # Mirror pipeline.py step 7 preprocessing: white-bg-to-alpha + tight crop.
    def _prep(img):
        return _crop_to_content(_white_bg_to_alpha(img))

    tex_images = {}
    if "front" in raw_views:
        tex_images["front"] = _prep(raw_views["front"])
    if "back" in raw_views:
        tex_images["back"] = _prep(raw_views["back"])
    for side_key in ("left", "right"):
        if side_key in raw_views:
            tex_images["side"] = _prep(raw_views[side_key])
            break
    if not tex_images:
        tex_images["front"] = _prep(next(iter(raw_views.values())))

    ref = tex_images.get("front") or next(iter(tex_images.values()))
    base_color = _sample_avg_color(ref)
    print(f"  base_color = ({base_color[0]:.2f}, {base_color[1]:.2f}, {base_color[2]:.2f})")
    print(f"  views passed to bake: {list(tex_images.keys())}")

    print("\n[step] Running texture bake via Blender")
    t0 = time.time()
    baked_glb, baked_png, msg = _texture_bake_with_png(
        str(glb_path),
        tex_images,
        args.texture_size,
        scripts_dir=_SCRIPTS,
        base_color=base_color,
    )
    elapsed = time.time() - t0
    print(f"  {msg}")
    print(f"  elapsed: {elapsed:.1f}s")

    if baked_glb is None:
        sys.exit("Texture bake failed.")

    out_glb = Path(args.output) if args.output else (
        _ROOT / "output" / name / "3dmodel" / f"{name}_textured_test.glb"
    )
    out_glb.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(baked_glb, out_glb)
    Path(baked_glb).unlink(missing_ok=True)

    if baked_png:
        out_png = out_glb.with_name(f"{out_glb.stem}.png")
        shutil.copy2(baked_png, out_png)
        Path(baked_png).unlink(missing_ok=True)
        print(f"  albedo -> {out_png}")

    print(f"\n[done] wrote {out_glb}")


def _parse(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="test_texture_bake",
        description="Isolated texture-bake smoke test (no Hunyuan3D).",
    )
    p.add_argument("--name", default="2-empalynx",
                   help="Creature name for default input/output paths.")
    p.add_argument("--glb", default=None,
                   help="Source GLB path (default: output/{name}/3dmodel/{name}.glb).")
    p.add_argument("--input-dir", default=None,
                   help="Reference image directory (default: input/{name}).")
    p.add_argument("--output", default=None,
                   help="Output GLB path (default: output/{name}/3dmodel/{name}_textured_test.glb).")
    p.add_argument("--texture-size", type=int, default=2048)
    return p.parse_args(argv)


if __name__ == "__main__":
    run(_parse())
