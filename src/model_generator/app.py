"""
Local Gradio UI: upload image → download GLB (offline).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import gradio as gr
from PIL import Image

from model_generator.engine_info import engine_banner_markdown, engine_version
from model_generator.paths import reference_model_path
from model_generator.pipeline import generate_glb_from_image, reference_status_message


def _project_output_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "output"


def run_generation(
    front: Image.Image | None,
    side: Image.Image | None,
    top: Image.Image | None,
    back: Image.Image | None,
    bottom: Image.Image | None,
    max_resolution: int,
    plane_scale: float,
    height_scale: float,
    vertical_asym: float,
    gray_depth: float,
    hull_rounding: float,
    mirror_side: bool,
) -> tuple[str | None, str]:
    if front is None:
        return None, "Upload a **front** image first."

    out_dir = _project_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=".glb", delete=False, dir=out_dir) as tmp:
        out_path = Path(tmp.name)

    try:
        path = generate_glb_from_image(
            front,
            out_path,
            side_image=side,
            max_resolution=int(max_resolution),
            plane_scale=float(plane_scale),
            height_scale=float(height_scale),
            vertical_asym=float(vertical_asym),
            gray_depth=float(gray_depth),
            hull_rounding=float(hull_rounding),
            mirror_side=bool(mirror_side),
            top_image=top if side is not None else None,
            back_image=back if side is not None else None,
            bottom_image=bottom if side is not None else None,
        )
        if reference_model_path() is not None:
            mode = "reference"
        elif side is not None:
            n_extra = sum(1 for x in (top, back, bottom) if x is not None)
            mode = f"multi-view hull ({n_extra} extra)" + (" + mirror" if mirror_side else "")
        else:
            mode = "single-view silhouette"
        return str(path), f"Saved: {path.name} ({mode})"
    except Exception as e:
        if out_path.exists():
            out_path.unlink(missing_ok=True)
        return None, f"Error: {e}"


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="modelGenerator") as demo:
        gr.Markdown(
            "### modelGenerator — image → GLB (offline)\n"
            + engine_banner_markdown()
            + "\n\n"
            + reference_status_message()
            + "\n\n"
            "**Hull (best):** **front** + **side** — use a **true profile** for side (depth = image width), not a 3/4 angle. "
            "Silhouettes are **tight-cropped** so wide margins do not crush depth. Add **top** / **back** / "
            "**bottom** to carve plan and rear/sole. See `assets/samples/good/README.md`.\n\n"
            "**Mirror side** only duplicates the **side** silhouette along depth (left/right profile "
            "symmetry). It does **not** mirror the **front** image. Default **off**; turn on only if "
            "you want that shortcut.\n\n"
            "**Rounding** (default **0.35**) tapers depth near silhouette edges so the **nape** and "
            "sides curve instead of staying flat. Also **auto-detects dark features** (eyes, mouth) in "
            "the front image and applies small surface recesses. Raise to **~0.5** for rounder heads.\n\n"
            "**Single image:** volumetric silhouette + sliders below (no hull).\n\n"
            "View axes: see `assets/samples/good/README.md`. **glTFast** in Unity."
        )
        with gr.Row():
            with gr.Column():
                front_in = gr.Image(type="pil", label="Front (−Z camera)")
                side_in = gr.Image(type="pil", label="Side (−X camera, optional)")
                gr.Markdown(
                    "**Optional (only with side):** top/bottom map **rows → depth (Z)**, **cols → width (X)**; "
                    "the app tries **transpose** automatically if it helps. **Side** image width sets body **length**."
                )
                with gr.Row():
                    top_in = gr.Image(type="pil", label="Top (−Y)")
                    back_in = gr.Image(type="pil", label="Back (+Z)")
                    bottom_in = gr.Image(type="pil", label="Bottom (+Y)")
                max_res = gr.Slider(
                    32,
                    128,
                    value=64,
                    step=8,
                    label="Resolution (grid / voxel grid size)",
                )
                plane = gr.Slider(
                    0.1,
                    3.0,
                    value=1.0,
                    step=0.05,
                    label="Scale (world units)",
                )
                height = gr.Slider(
                    0.05,
                    1.0,
                    value=0.3,
                    step=0.02,
                    label="Thickness (single-image mode only)",
                )
                v_asym = gr.Slider(
                    -1.0,
                    1.0,
                    value=0.0,
                    step=0.05,
                    label="Vertical asymmetry (single-image: top vs bottom thickness)",
                )
                g_dep = gr.Slider(
                    0.0,
                    0.5,
                    value=0.0,
                    step=0.02,
                    label="Luminance depth (single: Y thickness; hull: face relief ~0.15–0.25)",
                )
                rounding = gr.Slider(
                    0.0,
                    1.0,
                    value=0.35,
                    step=0.05,
                    label="Rounding (hull: rounds nape/sides + auto eye/mouth recess ~0.3-0.6)",
                )
                mirror_chk = gr.Checkbox(
                    value=False,
                    label="Mirror side along depth only (symmetric profile, not front)",
                )
                btn = gr.Button("Generate GLB")
            with gr.Column():
                out_file = gr.File(label="Download GLB", type="filepath")
                status = gr.Textbox(label="Status", interactive=False)

        btn.click(
            fn=run_generation,
            inputs=[
                front_in,
                side_in,
                top_in,
                back_in,
                bottom_in,
                max_res,
                plane,
                height,
                v_asym,
                g_dep,
                rounding,
                mirror_chk,
            ],
            outputs=[out_file, status],
        )
    return demo


def launch() -> None:
    demo = build_ui()
    demo.launch()


if __name__ == "__main__":
    launch()
