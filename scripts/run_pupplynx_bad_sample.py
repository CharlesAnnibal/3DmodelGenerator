"""
Regenerate Pupplynx from ``assets/samples/bad/images/`` using the same API as the Gradio app.

Usage (from ``modelGenerator``):

  python scripts/run_pupplynx_bad_sample.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from model_generator.engine_info import engine_version
from model_generator.pipeline import generate_glb_from_image


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    img_dir = root / "assets" / "samples" / "bad" / "images"
    out_dir = root / "assets" / "samples" / "bad" / "results"

    front = Image.open(img_dir / "front.png")
    side = Image.open(img_dir / "side.png")
    top = Image.open(img_dir / "top.png")
    back = Image.open(img_dir / "back.png")
    bottom = Image.open(img_dir / "bottom.png")

    out_dir.mkdir(parents=True, exist_ok=True)
    ver = engine_version()

    # Same defaults as Gradio: resolution 64, scale 1, luminance 0, rounding 0.35, no mirror.
    p1 = out_dir / "pupplynx_app_defaults.glb"
    generate_glb_from_image(
        front,
        p1,
        side_image=side,
        top_image=top,
        back_image=back,
        bottom_image=bottom,
        max_resolution=64,
        plane_scale=1.0,
        gray_depth=0.0,
        hull_rounding=0.35,
        mirror_side=False,
    )

    # Pure visual hull (no scalar sculpt) — compare if geometry looks cleaner.
    p2 = out_dir / "pupplynx_hull_only.glb"
    generate_glb_from_image(
        front,
        p2,
        side_image=side,
        top_image=top,
        back_image=back,
        bottom_image=bottom,
        max_resolution=64,
        plane_scale=1.0,
        gray_depth=0.0,
        hull_rounding=0.0,
        mirror_side=False,
    )

    manifest = out_dir / "pupplynx_run_manifest.txt"
    manifest.write_text(
        f"engine: model-generator {ver}\n"
        "app_defaults: max_resolution=64 plane_scale=1 gray_depth=0 hull_rounding=0.35\n"
        "hull_only: hull_rounding=0 hull_gray_depth=0 (binary hull, no sculpt field)\n",
        encoding="utf-8",
    )
    print(f"Wrote {p1.name}, {p2.name}, {manifest.name} (engine {ver})")


if __name__ == "__main__":
    main()
