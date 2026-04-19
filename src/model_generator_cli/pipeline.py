"""Per-creature 3D generation pipeline.

Orchestrates image loading, background removal, Hunyuan3D shape generation,
texture baking, leg-fix, and auto-rigging for a single creature.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image as PILImage

from model_generator.blender_tools import (
    find_blender_executable,
    autorig_via_blender,
    decimate_via_blender,
    fix_legs_via_blender,
)
from model_generator.image_utils import (
    maybe_rembg,
    deduplicate_mirrored_views,
)
from model_generator_cli.progress import step_status, warn, success, error

# ---------------------------------------------------------------------------
# Presets: (huggingface_repo, subfolder)
# ---------------------------------------------------------------------------

PRESETS_SINGLE = {
    "Hunyuan3D-2 (quality)": ("tencent/Hunyuan3D-2", "hunyuan3d-dit-v2-0"),
    "Hunyuan3D-2 Turbo (faster)": ("tencent/Hunyuan3D-2", "hunyuan3d-dit-v2-0-turbo"),
    "Hunyuan3D-2mini (low VRAM)": ("tencent/Hunyuan3D-2mini", "hunyuan3d-dit-v2-mini"),
}

PRESET_MV = ("tencent/Hunyuan3D-2mv", "hunyuan3d-dit-v2-mv")

# ---------------------------------------------------------------------------
# Lazy pipeline cache (avoids reloading multi-GB weights between creatures)
# ---------------------------------------------------------------------------

_shape_cache: dict[tuple[str, str, str, str], object] = {}


def _scripts_dir() -> Path:
    """Resolve ``modelGenerator/scripts/`` relative to this file."""
    return Path(__file__).resolve().parents[3] / "modelGenerator" / "scripts"


def _get_shape_pipeline(model_path: str, subfolder: str):
    """Load (or return cached) Hunyuan3D shape pipeline."""
    import torch
    from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    key = (model_path, subfolder, device, str(dtype))
    if key not in _shape_cache:
        _shape_cache[key] = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
            model_path,
            subfolder=subfolder,
            variant="fp16",
            device=device,
            dtype=dtype,
        )
    return _shape_cache[key]


# ---------------------------------------------------------------------------
# Texture bake helper that returns both GLB and PNG paths
# ---------------------------------------------------------------------------


def _white_bg_to_alpha(
    img: PILImage.Image,
    white_threshold: int = 240,
    shadow_brightness: int = 185,
    shadow_max_saturation: int = 25,
) -> PILImage.Image:
    """Convert background pixels (white + drop shadows) to transparent.

    Two classes of pixel are masked:
    - Near-white: all channels >= *white_threshold*.
    - Drop shadows: all channels >= *shadow_brightness* AND
      (max_channel - min_channel) < *shadow_max_saturation* — i.e. very
      desaturated / near-neutral gray.  These are the soft ground shadows
      common in illustration reference sheets.

    Using original pre-rembg images is preferred because rembg destroys alpha
    on light-coloured cartoon creatures with white backgrounds.
    """
    import numpy as _np
    arr = _np.asarray(img.convert("RGBA")).copy()
    r = arr[:, :, 0].astype(_np.int32)
    g = arr[:, :, 1].astype(_np.int32)
    b = arr[:, :, 2].astype(_np.int32)

    white_mask = (r >= white_threshold) & (g >= white_threshold) & (b >= white_threshold)

    bright = (r >= shadow_brightness) & (g >= shadow_brightness) & (b >= shadow_brightness)
    saturation = (
        _np.maximum(_np.maximum(r, g), b) - _np.minimum(_np.minimum(r, g), b)
    )
    shadow_mask = bright & (saturation < shadow_max_saturation)

    arr[white_mask | shadow_mask, 3] = 0
    return PILImage.fromarray(arr, "RGBA")


def _crop_to_content(img: PILImage.Image, padding: float = 0.03) -> PILImage.Image:
    """Crop an RGBA image to the bounding box of its opaque pixels.

    The orthographic UV projection maps the mesh bounding-box to UV [0,1].
    If the creature sits in only a small corner of the source image (common
    with character-sheet exports that add lots of white margin), the projected
    UV coords hit transparent pixels and contribute zero weight to the bake.

    This crops the image so the creature fills the full [0,1] UV range,
    matching what the projection expects.  A small *padding* (fraction of
    the content size) is added on all sides so border pixels don't fall
    exactly at the CLIP edge.
    """
    import numpy as _np
    arr = _np.asarray(img.convert("RGBA"))
    alpha = arr[:, :, 3]
    rows_with_content = _np.any(alpha > 10, axis=1)
    cols_with_content = _np.any(alpha > 10, axis=0)
    if not rows_with_content.any() or not cols_with_content.any():
        return img  # all transparent — nothing to crop
    rmin = int(_np.where(rows_with_content)[0][0])
    rmax = int(_np.where(rows_with_content)[0][-1])
    cmin = int(_np.where(cols_with_content)[0][0])
    cmax = int(_np.where(cols_with_content)[0][-1])
    H, W = arr.shape[:2]
    pad_r = max(1, int(padding * (rmax - rmin + 1)))
    pad_c = max(1, int(padding * (cmax - cmin + 1)))
    rmin = max(0, rmin - pad_r)
    rmax = min(H - 1, rmax + pad_r)
    cmin = max(0, cmin - pad_c)
    cmax = min(W - 1, cmax + pad_c)
    return img.crop((cmin, rmin, cmax + 1, rmax + 1))


def _sample_avg_color(img: PILImage.Image) -> tuple[float, float, float]:
    """Return the average sRGB color of opaque pixels in 0–1 range.

    Used as a base-coat fallback for mesh surfaces that face none of the
    orthographic projection cameras (top of head, belly underside, etc.).
    """
    import numpy as _np
    arr = _np.asarray(img.convert("RGBA"))
    mask = arr[:, :, 3] > 10
    if not mask.any():
        return 0.70, 0.60, 0.50  # neutral tan fallback
    rgb = arr[:, :, :3][mask].astype(float)
    avg = rgb.mean(axis=0)
    return float(avg[0] / 255), float(avg[1] / 255), float(avg[2] / 255)


def _texture_bake_with_png(
    input_glb: str,
    images: dict[str, PILImage.Image],
    texture_size: int,
    *,
    scripts_dir: Path,
    base_color: tuple[float, float, float] | None = None,
) -> tuple[str | None, str | None, str]:
    """Bake texture via triplanar projection, returning ``(glb_path, png_path, message)``.

    Uses the pure-Python triplanar script (``texture_bake_python.py``) which
    assigns each face to its dominant view and samples directly from a composite
    texture.  No Blender dependency, no UV atlas unwrap.
    """
    script = scripts_dir / "texture_bake_python.py"
    if not script.is_file():
        return None, None, f"Texture bake skipped: script not found at {script}."
    if not images:
        return None, None, "Texture bake skipped: no images."

    tmp_imgs: list[Path] = []
    fd, out_glb = tempfile.mkstemp(suffix=".glb", prefix="creature_textured_")
    os.close(fd)
    fd, out_png = tempfile.mkstemp(suffix=".png", prefix="creature_albedo_")
    os.close(fd)

    try:
        cmd: list[str] = [
            sys.executable,
            str(script),
            str(Path(input_glb).resolve()),
            str(Path(out_glb).resolve()),
            str(Path(out_png).resolve()),
            str(texture_size),
        ]
        for key, pil in images.items():
            fd2, img_path = tempfile.mkstemp(suffix=".png", prefix=f"tex_{key}_")
            os.close(fd2)
            pil.save(img_path)
            tmp_imgs.append(Path(img_path))
            cmd.append(f"{key}={img_path}")

        if base_color is not None:
            cmd.append(
                f"base_color={base_color[0]:.4f},{base_color[1]:.4f},{base_color[2]:.4f}"
            )

        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=1800, check=False,
        )

        bake_log = (proc.stdout or "") + (proc.stderr or "")
        for ln in bake_log.splitlines():
            if "[bake_py]" in ln:
                print(f"    {ln.strip()}", flush=True)

        glb_ok = Path(out_glb).is_file() and Path(out_glb).stat().st_size > 0
        png_ok = Path(out_png).is_file() and Path(out_png).stat().st_size > 0

        if proc.returncode != 0 or not glb_ok:
            Path(out_glb).unlink(missing_ok=True)
            Path(out_png).unlink(missing_ok=True)
            detail = bake_log.strip()
            if detail:
                lines = [
                    ln for ln in detail.splitlines()
                    if "[bake_py]" in ln or "Error" in ln
                ]
                detail = lines[-1] if lines else detail.splitlines()[-1]
            return None, None, f"Texture bake failed. {detail}".strip()

        return (
            str(out_glb),
            str(out_png) if png_ok else None,
            "Texture baked via triplanar projection.",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        Path(out_glb).unlink(missing_ok=True)
        Path(out_png).unlink(missing_ok=True)
        return None, None, f"Texture bake failed: {exc}"
    finally:
        for p in tmp_imgs:
            p.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def process_creature(
    name: str,
    images: dict[str, Path],
    output_dir: Path,
    *,
    preset: str,
    steps: int,
    octree_resolution: int,
    num_chunks: int,
    seed: int,
    texture_size: int,
    rig_profile: str,
    use_rembg: bool,
    with_texture: bool,
    fix_legs: bool,
    auto_rig: bool,
    target_height: float = 1.0,
    run_acceptance: bool = True,
    strict_acceptance: bool = False,
    export_fbx: bool = True,
) -> None:
    """Generate a 3D model for a single creature.

    *images* maps view names (``front``, ``back``, ``left``, ``right``) to
    image file paths.  Outputs are written into
    ``output_dir / name / {3dmodel, textures}/``.
    """
    import torch

    scripts = _scripts_dir()
    model_dir = output_dir / name / "3dmodel"
    tex_dir = output_dir / name / "textures"
    model_dir.mkdir(parents=True, exist_ok=True)
    tex_dir.mkdir(parents=True, exist_ok=True)

    temp_files: list[Path] = []

    try:
        # -- 1. Load images ------------------------------------------------
        step_status(name, "Loading images")
        views: dict[str, PILImage.Image] = {}
        for view_name, path in images.items():
            views[view_name] = PILImage.open(path).convert("RGBA")

        if "side" in views and "left" not in views:
            views["left"] = views.pop("side")

        # Keep originals for texture baking (rembg can destroy alpha on
        # light-coloured creatures against white backgrounds).
        original_views: dict[str, PILImage.Image] = {k: v.copy() for k, v in views.items()}

        # -- 2. Remove backgrounds -----------------------------------------
        if use_rembg:
            step_status(name, "Removing backgrounds")
            views = {k: maybe_rembg(v, True) for k, v in views.items()}

        # -- 3. Shape generation -------------------------------------------
        step_status(name, "Generating shape mesh")
        is_multiview = len(views) >= 2

        if is_multiview:
            views, mirror_warnings = deduplicate_mirrored_views(views)
            for w in mirror_warnings:
                warn(name, w)

            if (
                "front" in views and "back" in views
                and "left" not in views and "right" not in views
            ):
                raise RuntimeError(
                    f"{name}: front+back only is ambiguous and can invent extra "
                    "limbs. Provide front + left/right, or all four views."
                )

            mp, sub = PRESET_MV
            pipe = _get_shape_pipeline(mp, sub)
            mesh = pipe(
                image=views,
                num_inference_steps=steps,
                octree_resolution=octree_resolution,
                num_chunks=num_chunks,
                generator=torch.manual_seed(seed),
                output_type="trimesh",
            )[0]
        else:
            mp, sub = PRESETS_SINGLE[preset]
            pipe = _get_shape_pipeline(mp, sub)
            pil = next(iter(views.values()))
            mesh = pipe(
                image=pil,
                num_inference_steps=steps,
                octree_resolution=octree_resolution,
                num_chunks=num_chunks,
                generator=torch.manual_seed(seed),
                output_type="trimesh",
            )[0]

        # -- 4. Export raw GLB to temp file --------------------------------
        fd, raw_glb = tempfile.mkstemp(suffix=".glb", prefix=f"{name}_raw_")
        os.close(fd)
        raw_glb_path = Path(raw_glb)
        temp_files.append(raw_glb_path)
        mesh.export(str(raw_glb_path))
        current_glb = str(raw_glb_path)

        # -- 4b. Scale normalization ---------------------------------------
        step_status(name, f"Normalizing scale to {target_height:.2f} m")
        try:
            import trimesh as _trimesh
            import numpy as _np
            _raw = _trimesh.load(current_glb, force="mesh", process=False)
            _verts = _np.asarray(_raw.vertices)
            _bbox_z = float(_verts[:, 2].max() - _verts[:, 2].min())
            if _bbox_z > 1e-6:
                _scale = target_height / _bbox_z
                _raw.apply_scale(_scale)
                fd2, _scaled_glb = tempfile.mkstemp(suffix=".glb", prefix=f"{name}_scaled_")
                os.close(fd2)
                _scaled_path = Path(_scaled_glb)
                temp_files.append(_scaled_path)
                _raw.export(str(_scaled_path))
                current_glb = str(_scaled_path)
            else:
                warn(name, "Scale normalization skipped: mesh height is near zero.")
        except Exception as _exc:
            warn(name, f"Scale normalization failed: {_exc}")

        # -- 4c. Mesh decimation -------------------------------------------
        # Target 100 K faces so that after UV-seam vertex splitting during
        # Blender GLB export (typically ~3× inflation) the vertex count stays
        # well under the 500 K acceptance cap.
        #
        # Decimating here (before texture bake and rigging) is critical:
        # texture baking on a 300K+ face mesh can take tens of minutes.
        # Strategy: try trimesh first (fast, in-process, no Blender startup);
        # if it has no effect — fast_simplification/open3d/pymeshlab are all
        # optional and often missing — fall back to Blender's Decimate
        # modifier which works without extra Python deps.
        _TARGET_FACES = 100_000
        _decimated_ok = False
        try:
            import trimesh as _trimesh
            _dec_mesh = _trimesh.load(current_glb, force="mesh", process=False)
            _nfaces = len(_dec_mesh.faces)
            if _nfaces > _TARGET_FACES:
                step_status(name, f"Decimating mesh ({_nfaces:,} -> {_TARGET_FACES:,} faces)")
                _dec_mesh = _dec_mesh.simplify_quadric_decimation(_TARGET_FACES)
                _nfaces_after = len(_dec_mesh.faces)
                if _nfaces_after < _nfaces:
                    fd3, _dec_glb = tempfile.mkstemp(suffix=".glb", prefix=f"{name}_dec_")
                    os.close(fd3)
                    _dec_path = Path(_dec_glb)
                    temp_files.append(_dec_path)
                    _dec_mesh.export(str(_dec_path))
                    current_glb = str(_dec_path)
                    _decimated_ok = True
            else:
                _decimated_ok = True  # already under target
        except Exception as _exc:
            warn(name, f"Trimesh decimation failed: {_exc}. Will try Blender.")

        if not _decimated_ok:
            warn(name, "Trimesh decimation had no effect — falling back to Blender.")
            step_status(name, f"Decimating mesh via Blender (target {_TARGET_FACES:,} faces)")
            _bd_glb, _bd_msg = decimate_via_blender(
                current_glb, _TARGET_FACES, scripts_dir=scripts,
            )
            if _bd_glb is not None:
                temp_files.append(Path(_bd_glb))
                current_glb = _bd_glb
            else:
                warn(name, f"Blender decimation also failed: {_bd_msg}")

        # -- 5. Fix merged legs --------------------------------------------
        if fix_legs:
            step_status(name, "Fixing merged legs")
            fixed, fix_msg = fix_legs_via_blender(
                current_glb, rig_profile, scripts_dir=scripts,
            )
            if fixed is not None:
                temp_files.append(Path(fixed))
                current_glb = fixed
            else:
                warn(name, fix_msg)

        # -- 6. Auto-rig untextured model ----------------------------------
        if auto_rig:
            step_status(name, "Auto-rigging untextured model")
            rigged, rigged_fbx, rig_manifest, rig_msg = autorig_via_blender(
                current_glb, rig_profile, scripts_dir=scripts, export_fbx=export_fbx,
            )
            if rigged is not None:
                shutil.copy2(rigged, model_dir / f"{name}.glb")
                temp_files.append(Path(rigged))
                if rigged_fbx:
                    shutil.copy2(rigged_fbx, model_dir / f"{name}_rigged.fbx")
                    temp_files.append(Path(rigged_fbx))
                if rig_manifest:
                    shutil.copy2(rig_manifest, model_dir / f"{name}_rig_manifest.json")
                    temp_files.append(Path(rig_manifest))
            else:
                warn(name, rig_msg)

        # -- 7. Texture bake -----------------------------------------------
        textured_glb: str | None = None
        if with_texture:
            step_status(name, "Baking texture")
            # Use original (pre-rembg) images with white-to-transparent
            # conversion.  rembg destroys alpha on light-coloured cartoon
            # creatures against white backgrounds, producing a black bake.
            def _prep_tex(img: PILImage.Image) -> PILImage.Image:
                """Strip background then crop tight to creature content."""
                return _crop_to_content(_white_bg_to_alpha(img))

            tex_images: dict[str, PILImage.Image] = {}
            if "front" in original_views:
                tex_images["front"] = _prep_tex(original_views["front"])
            if "back" in original_views:
                tex_images["back"] = _prep_tex(original_views["back"])
            for side_key in ("left", "right"):
                if side_key in original_views:
                    tex_images["side"] = _prep_tex(original_views[side_key])
                    break
            if not tex_images:
                tex_images["front"] = _prep_tex(next(iter(original_views.values())))

            # Sample average creature colour as base coat for surfaces that
            # face none of the orthographic projection cameras.
            _ref_img = tex_images.get("front") or next(iter(tex_images.values()))
            _base_color = _sample_avg_color(_ref_img)

            baked_glb, baked_png, tex_msg = _texture_bake_with_png(
                current_glb, tex_images, texture_size,
                scripts_dir=scripts,
                base_color=_base_color,
            )
            if baked_glb is not None:
                textured_glb = baked_glb
                temp_files.append(Path(baked_glb))
                if baked_png is not None:
                    shutil.copy2(baked_png, tex_dir / f"{name}.png")
                    temp_files.append(Path(baked_png))
            else:
                warn(name, tex_msg)
                try:
                    from model_generator.cpu_texture import project_texture

                    mesh = project_texture(mesh, next(iter(views.values())))
                    fd, cpu_glb = tempfile.mkstemp(
                        suffix=".glb", prefix=f"{name}_cpu_tex_",
                    )
                    os.close(fd)
                    cpu_path = Path(cpu_glb)
                    temp_files.append(cpu_path)
                    mesh.export(str(cpu_path))
                    textured_glb = str(cpu_path)
                except Exception as exc:
                    warn(name, f"CPU texture fallback failed: {exc}")

        # -- 8. Save textured GLB (texture embedded, before rigging) ----------
        if textured_glb is not None:
            step_status(name, "Saving textured model (GLB)")
            shutil.copy2(textured_glb, model_dir / f"{name}_textured.glb")

        # -- 9. Auto-rig textured model ------------------------------------
        if auto_rig and textured_glb is not None:
            step_status(name, "Auto-rigging textured model")
            rigged_tex, rigged_tex_fbx, _tex_manifest, rig_tex_msg = autorig_via_blender(
                textured_glb, rig_profile, scripts_dir=scripts, export_fbx=export_fbx,
            )
            if rigged_tex is not None:
                shutil.copy2(rigged_tex, model_dir / f"{name}_textured_rigged.glb")
                temp_files.append(Path(rigged_tex))
                if rigged_tex_fbx:
                    shutil.copy2(rigged_tex_fbx, model_dir / f"{name}_textured_rigged.fbx")
                    temp_files.append(Path(rigged_tex_fbx))
            else:
                warn(name, rig_tex_msg)

        # -- 10. Acceptance test -------------------------------------------
        if run_acceptance:
            step_status(name, "Running acceptance checks")
            try:
                from model_generator_cli.acceptance import run_acceptance as _run_acceptance
                result = _run_acceptance(
                    name,
                    output_dir,
                    reference_images=images,
                    render=True,
                    target_height=target_height,
                )
                if result.passed:
                    success(name, f"Acceptance PASS (score: {result.score:.2f})")
                else:
                    fails = [c for c in result.checks if not c.passed]
                    critical = [c for c in fails if c.severity == "CRITICAL"]
                    high = [c for c in fails if c.severity == "HIGH"]
                    warn(name, f"Acceptance FAIL (score: {result.score:.2f}) — "
                         f"{len(critical)} critical, {len(high)} high failures")
                    for c in critical + high:
                        warn(name, f"  {c.id} {c.name}: {c.value} (expected {c.threshold})")
                    if strict_acceptance:
                        raise RuntimeError(
                            f"Acceptance failed for {name}: "
                            f"{len(critical)} critical, {len(high)} high checks failed"
                        )
            except ImportError:
                warn(name, "Acceptance module not available — skipping checks")
            except RuntimeError:
                raise
            except Exception as exc:
                warn(name, f"Acceptance check error: {exc}")

        step_status(name, "Done")

    finally:
        # -- 11. Clean up temp files ----------------------------------------
        for p in temp_files:
            p.unlink(missing_ok=True)
