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
    autorig_via_blender,
    cleanup_mesh_via_blender,
    decimate_via_blender,
    fix_legs_via_blender,
    fix_arms_via_blender,
    render_uv_lookup_via_blender,
    unwrap_uv_via_blender,
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
    return Path(__file__).resolve().parents[2] / "modelGenerator" / "scripts"


def _get_shape_pipeline(model_path: str, subfolder: str):
    """Load (or return cached) Hunyuan3D shape pipeline."""
    import torch
    from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline

    cuda_available = torch.cuda.is_available()
    device = "cuda" if cuda_available else "cpu"
    dtype = torch.float16 if cuda_available else torch.float32
    key = (model_path, subfolder, device, str(dtype))
    if key not in _shape_cache:
        load_device = "cpu" if cuda_available else "cpu"
        pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
            model_path,
            subfolder=subfolder,
            variant="fp16",
            device=load_device,
            dtype=dtype,
        )
        if cuda_available:
            # Enable FlashVDM turbo decoder BEFORE setting device or hooks so the
            # replacement turbo VAE is loaded to CPU (not GPU).  FlashVDM uses
            # adaptive KV selection and is 5-10x faster for latents2mesh.
            try:
                pipe.enable_flashvdm(mc_algo="mc")
            except Exception as _fvdm_err:
                warn("pipeline", f"FlashVDM unavailable, using default decoder: {_fvdm_err}")

            from accelerate import cpu_offload_with_hook
            # Hook only conditioner and model (DiT) — NOT the VAE.
            # The VAE hook would return it to CPU after decode, forcing latents2mesh
            # (volume decoder) to run on CPU and taking hours.
            # Instead we move the VAE to GPU manually in the _export patch below.
            hook = None
            for component_name in ["conditioner", "model"]:
                component = getattr(pipe, component_name, None)
                if component is not None:
                    _, hook = cpu_offload_with_hook(component, "cuda:0", prev_module_hook=hook)
            # __call__ uses self.device to decide where to create latents/timesteps.
            pipe.device = torch.device("cuda:0")
            # encode_cond calls conditioner.unconditional_embedding() AFTER the hook
            # has already moved the conditioner back to CPU, so those tensors are on
            # CPU while cond tensors from the first conditioner call are on GPU.
            # torch.cat in cat_recursive then fails with a device mismatch.
            # Fix: move every tensor in the returned cond dict to cuda:0.
            orig_encode_cond = pipe.encode_cond
            def _encode_cond_on_gpu(*args, **kwargs):
                result = orig_encode_cond(*args, **kwargs)
                def _to_cuda(obj):
                    if isinstance(obj, torch.Tensor):
                        return obj.to("cuda:0")
                    if isinstance(obj, dict):
                        return {k: _to_cuda(v) for k, v in obj.items()}
                    return obj
                return _to_cuda(result)
            pipe.encode_cond = _encode_cond_on_gpu
            # Move VAE to GPU for the full _export call so both decode and
            # latents2mesh (volume_decoder + geo_decoder) run on GPU.
            # DiT is back on CPU by then so VRAM is free for the VAE (~1 GB).
            orig_export = pipe._export
            def _export_gpu_vae(latents, *args, **kwargs):
                pipe.vae.to("cuda:0")
                torch.cuda.empty_cache()
                try:
                    return orig_export(latents, *args, **kwargs)
                finally:
                    pipe.vae.to("cpu")
                    torch.cuda.empty_cache()
            pipe._export = _export_gpu_vae
        _shape_cache[key] = pipe
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
    texture_mode: str = "cylindrical",
    use_mesh_uv: bool = False,
) -> tuple[str | None, str | None, str]:
    """Bake texture via triplanar projection, returning ``(glb_path, png_path, message)``.

    Uses the pure-Python triplanar script (``texture_bake_python.py``) which
    assigns each face to its dominant view and samples directly from a composite
    texture.  No Blender dependency for the bake itself; optional
    ``use_mesh_uv`` (cylindrical only) rasterizes using UVs from the input GLB
    (after Blender Smart UV in the pipeline).
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
        cmd.append(f"mode={texture_mode}")
        if use_mesh_uv and texture_mode == "cylindrical":
            cmd.append("use_mesh_uv=1")

        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=3600, check=False,
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
    fix_arms: bool,
    auto_rig: bool,
    target_height: float = 1.0,
    run_acceptance: bool = True,
    strict_acceptance: bool = False,
    export_fbx: bool = True,
    texture_images: dict[str, Path] | None = None,
    retexture_only: bool = False,
    texture_mode: str = "cylindrical",
    texture_overlap_repair: bool = True,
    blender_uv_unwrap: bool = True,
    controlled_semantic_texture: bool = True,
    rig_anchors: dict | None = None,
) -> None:
    """Generate a 3D model for a single creature.

    *images* maps view names (``front``, ``back``, ``left``, ``right``) to
    image file paths used for shape generation.

    *texture_images* is an optional wider set of images used only for texture
    baking — useful when shape was generated from a single 3/4 image but
    back/side references are available for better coverage.  Falls back to
    *images* when not provided.

    Outputs are written into ``output_dir / name / {3dmodel, textures}/``.
    """
    scripts = _scripts_dir()
    model_dir = output_dir / name / "3dmodel"
    tex_dir = output_dir / name / "textures"
    model_dir.mkdir(parents=True, exist_ok=True)
    tex_dir.mkdir(parents=True, exist_ok=True)

    temp_files: list[Path] = []

    try:
        if retexture_only:
            # -- Retexture-only: skip shape generation, reuse existing mesh --
            _cand_textured = model_dir / f"{name}_textured.glb"
            _cand_base     = model_dir / f"{name}.glb"
            if _cand_textured.is_file():
                current_glb = str(_cand_textured)
            elif _cand_base.is_file():
                current_glb = str(_cand_base)
            else:
                raise RuntimeError(
                    f"No existing model found at {_cand_textured} or {_cand_base}. "
                    "Run full generation first."
                )
            step_status(name, f"Retexture-only: using {Path(current_glb).name}")
        else:
            import torch

            # -- 1. Load images --------------------------------------------
            step_status(name, "Loading images")
            views: dict[str, PILImage.Image] = {}
            for view_name, path in images.items():
                views[view_name] = PILImage.open(path).convert("RGBA")

            if "side" in views and "left" not in views:
                views["left"] = views.pop("side")

            # Keep originals for texture baking (rembg can destroy alpha on
            # light-coloured creatures against white backgrounds).
            original_views: dict[str, PILImage.Image] = {k: v.copy() for k, v in views.items()}

            # -- 2. Remove backgrounds -------------------------------------
            if use_rembg:
                step_status(name, "Removing backgrounds")
                views = {k: maybe_rembg(v, True) for k, v in views.items()}

            # -- 3. Shape generation ---------------------------------------
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

            # -- 4. Export raw GLB to temp file ----------------------------
            fd, raw_glb = tempfile.mkstemp(suffix=".glb", prefix=f"{name}_raw_")
            os.close(fd)
            raw_glb_path = Path(raw_glb)
            temp_files.append(raw_glb_path)
            mesh.export(str(raw_glb_path))
            current_glb = str(raw_glb_path)

            # -- 4b. Scale normalization -----------------------------------
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

            # -- 4c. Mesh decimation ---------------------------------------
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

            # -- 5. Fix merged legs ----------------------------------------
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

            # -- 5b. Fix merged / flat arms --------------------------------
            if fix_arms:
                step_status(name, "Fixing merged/flat arms")
                arm_fixed, arm_msg = fix_arms_via_blender(
                    current_glb, rig_profile, scripts_dir=scripts,
                )
                if arm_fixed is not None:
                    temp_files.append(Path(arm_fixed))
                    current_glb = arm_fixed
                else:
                    warn(name, arm_msg)

            # -- 6. Mesh cleanup before the final unwrap --------------------
            step_status(name, "Cleaning mesh artifacts")
            cleaned, clean_msg = cleanup_mesh_via_blender(current_glb, scripts_dir=scripts)
            if cleaned is not None:
                temp_files.append(Path(cleaned))
                current_glb = cleaned
            else:
                warn(name, clean_msg)

            # Save the cleaned, untextured mesh. Rigging is intentionally
            # deferred until after texture generation so the final exported GLB
            # uses the post-cleanup, post-unwrap mesh.
            shutil.copy2(current_glb, model_dir / f"{name}.glb")

        # -- 7. Texture bake -----------------------------------------------
        textured_glb: str | None = None
        if with_texture:
            step_status(name, "Baking texture")
            # Use original (pre-rembg) images with white-to-transparent
            # conversion.  rembg destroys alpha on light-coloured cartoon
            # creatures against white backgrounds, producing a black bake.
            def _prep_tex(img: PILImage.Image) -> PILImage.Image:
                """Strip background, crop tight, sharpen, and erode alpha fringe."""
                from PIL import ImageFilter
                result = _crop_to_content(_white_bg_to_alpha(img))
                # A2: unsharp-mask sharpening on RGB channels only
                rgb = result.convert("RGB")
                rgb = rgb.filter(ImageFilter.UnsharpMask(radius=1.5, percent=120, threshold=3))
                alpha = result.split()[3]
                result = rgb.convert("RGBA")
                result.putalpha(alpha)
                # A3: erode alpha fringe by ~1 pixel using MinFilter on the alpha channel
                alpha_eroded = alpha.filter(ImageFilter.MinFilter(size=3))
                r, g, b, _ = result.split()
                result = PILImage.merge("RGBA", (r, g, b, alpha_eroded))
                return result

            # texture_images may include extra views (back, side) even when
            # shape was generated from a single image.
            tex_source: dict[str, PILImage.Image] = {}
            _tex_paths = texture_images if texture_images else images
            for _vname, _vpath in _tex_paths.items():
                tex_source[_vname] = PILImage.open(_vpath).convert("RGBA")

            tex_images: dict[str, PILImage.Image] = {}
            if "front" in tex_source:
                tex_images["front"] = _prep_tex(tex_source["front"])
            if "back" in tex_source:
                tex_images["back"] = _prep_tex(tex_source["back"])
            for side_key in ("left", "right", "side"):
                if side_key in tex_source:
                    tex_images["side"] = _prep_tex(tex_source[side_key])
                    break
            if "three_quarter" in tex_source:
                tex_images["three_quarter"] = _prep_tex(tex_source["three_quarter"])
            if not tex_images:
                tex_images["front"] = _prep_tex(next(iter(tex_source.values())))

            # A1: synthesise an explicit right-side image by mirroring left/side
            # so the mirror is auditable on disk rather than invisible inside the
            # bake script.  Only generated when no right image was already provided.
            if "right" not in tex_images:
                _side_src = tex_images.get("side") or tex_images.get("left")
                if _side_src is not None:
                    from PIL import ImageOps
                    tex_images["right"] = ImageOps.mirror(_side_src)

            # Sample average creature colour as base coat for surfaces that
            # face none of the orthographic projection cameras.
            _ref_img = tex_images.get("front") or next(iter(tex_images.values()))
            _base_color = _sample_avg_color(_ref_img)

            use_mesh_uv_for_bake = False
            if blender_uv_unwrap and texture_mode == "cylindrical":
                step_status(name, "Final UV unwrap (Smart UV + pack)")
                uw_glb, uw_msg = unwrap_uv_via_blender(current_glb, scripts_dir=scripts)
                if uw_glb:
                    temp_files.append(Path(uw_glb))
                    current_glb = uw_glb
                    use_mesh_uv_for_bake = True
                else:
                    warn(name, uw_msg)

            baked_glb: str | None = None
            baked_png: str | None = None
            tex_msg = "Texture not generated."
            semantic_texture_used = False

            if controlled_semantic_texture and use_mesh_uv_for_bake:
                try:
                    from model_generator_cli.diffusion_texture import (
                        reembed_texture_in_glb,
                    )
                    from model_generator_cli.semantic_texture import (
                        generate_semantic_texture,
                    )

                    step_status(name, "Rendering UV lookup views")
                    uv_dir = output_dir / name / "uv_lookup"
                    uv_files, uv_msg = render_uv_lookup_via_blender(
                        current_glb, uv_dir, size=768, scripts_dir=scripts,
                    )
                    if uv_files is None:
                        warn(name, uv_msg)
                    else:
                        step_status(name, "Semantic texture paint (controlled)")
                        _semantic_paths: dict[str, Path] = {}
                        for _k, _p in _tex_paths.items():
                            if _k in ("front", "back", "left", "right", "side"):
                                _semantic_paths[_k] = _p
                        _semantic_tex = generate_semantic_texture(
                            _semantic_paths,
                            uv_files,
                            base_color=_base_color,
                            texture_size=texture_size,
                        )
                        fd_s, _sem_glb = tempfile.mkstemp(
                            suffix=".glb", prefix=f"{name}_semantic_",
                        )
                        os.close(fd_s)
                        fd_p, _sem_png = tempfile.mkstemp(
                            suffix=".png", prefix=f"{name}_semantic_",
                        )
                        os.close(fd_p)
                        _semantic_tex.save(_sem_png)
                        if reembed_texture_in_glb(current_glb, _semantic_tex, _sem_glb):
                            baked_glb = _sem_glb
                            baked_png = _sem_png
                            semantic_texture_used = True
                            tex_msg = "Texture painted via controlled semantic UV lookup."
                            temp_files.append(Path(_sem_glb))
                        else:
                            Path(_sem_glb).unlink(missing_ok=True)
                            Path(_sem_png).unlink(missing_ok=True)
                            warn(name, "Semantic texture re-embed failed; falling back to projection bake")
                except Exception as _sem_exc:
                    warn(name, f"Semantic texture paint skipped: {_sem_exc}")

            if baked_glb is None:
                step_status(name, "Projection texture bake (fallback)")
                baked_glb, baked_png, tex_msg = _texture_bake_with_png(
                    current_glb, tex_images, texture_size,
                    scripts_dir=scripts,
                    base_color=_base_color,
                    texture_mode=texture_mode,
                    use_mesh_uv=use_mesh_uv_for_bake,
                )
            if baked_glb is not None:
                textured_glb = baked_glb
                temp_files.append(Path(baked_glb))
                if baked_png is not None:
                    try:
                        from model_generator_cli.diffusion_texture import (
                            enhance_texture, fallback_coverage, reembed_texture_in_glb,
                        )
                        _baked_pil = PILImage.open(baked_png)
                        _cov = fallback_coverage(_baked_pil, _base_color)
                        if _cov >= 0.15 and not semantic_texture_used:
                            step_status(name, f"Diffusion: filling {_cov:.0%} fallback coverage")
                            _enh_pil, _enhanced = enhance_texture(
                                _baked_pil, _base_color, name,
                            )
                            if _enhanced:
                                _enh_pil.save(baked_png)
                                fd_e, _enh_glb = tempfile.mkstemp(
                                    suffix=".glb", prefix=f"{name}_enh_",
                                )
                                os.close(fd_e)
                                _enh_path = Path(_enh_glb)
                                if reembed_texture_in_glb(baked_glb, _enh_pil, str(_enh_path)):
                                    temp_files.append(_enh_path)
                                    textured_glb = str(_enh_path)
                                else:
                                    _enh_path.unlink(missing_ok=True)
                    except Exception as _enh_exc:
                        warn(name, f"Diffusion texture enhancement skipped: {_enh_exc}")
                    if texture_overlap_repair and not semantic_texture_used:
                        try:
                            from model_generator_cli.diffusion_texture import (
                                reembed_texture_in_glb,
                            )
                            from model_generator_cli.texture_overlap_repair import (
                                repair_triplanar_overlap,
                            )

                            step_status(
                                name,
                                "Texture overlap repair (atlas band smooth)",
                            )
                            _repair_pil = repair_triplanar_overlap(
                                PILImage.open(baked_png)
                            )
                            _repair_pil.save(baked_png)
                            fd_ov, _ov_glb = tempfile.mkstemp(
                                suffix=".glb", prefix=f"{name}_ovrepair_",
                            )
                            os.close(fd_ov)
                            _ov_path = Path(_ov_glb)
                            if reembed_texture_in_glb(
                                textured_glb,
                                _repair_pil,
                                str(_ov_path),
                            ):
                                temp_files.append(_ov_path)
                                textured_glb = str(_ov_path)
                            else:
                                _ov_path.unlink(missing_ok=True)
                                warn(
                                    name,
                                    "Overlap repair re-embed failed; using prior GLB",
                                )
                        except Exception as _ov_exc:
                            warn(name, f"Texture overlap repair skipped: {_ov_exc}")
                    shutil.copy2(baked_png, tex_dir / f"{name}.png")
                    temp_files.append(Path(baked_png))
            else:
                warn(name, tex_msg)
                try:
                    from model_generator.cpu_texture import project_texture

                    _fallback_views = locals().get("views") or {}
                    if not _fallback_views:
                        raise RuntimeError("no in-memory views for CPU fallback")
                    mesh = project_texture(mesh, next(iter(_fallback_views.values())))
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
                    try:
                        _mesh_obj = mesh
                    except NameError:
                        _mesh_obj = None
                    try:
                        from model_generator_cli.diffusion_texture import (
                            generate_pbr_texture, reembed_texture_in_glb,
                        )
                        step_status(name, "Generating texture via diffusion (last-resort)")
                        _diff_tex = generate_pbr_texture(name, size=texture_size)
                        fd_d, _diff_glb = tempfile.mkstemp(
                            suffix=".glb", prefix=f"{name}_diff_",
                        )
                        os.close(fd_d)
                        _diff_path = Path(_diff_glb)
                        _applied = False
                        if _mesh_obj is not None:
                            try:
                                from model_generator.cpu_texture import project_texture
                                _proj_mesh = project_texture(_mesh_obj, _diff_tex)
                                _proj_mesh.export(str(_diff_path))
                                _applied = (
                                    _diff_path.is_file()
                                    and _diff_path.stat().st_size > 0
                                )
                            except Exception:
                                pass
                        if not _applied:
                            _applied = reembed_texture_in_glb(
                                current_glb, _diff_tex, str(_diff_path),
                            )
                        if _applied:
                            temp_files.append(_diff_path)
                            textured_glb = str(_diff_path)
                            _diff_tex.save(str(tex_dir / f"{name}.png"))
                        else:
                            _diff_path.unlink(missing_ok=True)
                    except Exception as _diff_exc:
                        warn(name, f"Diffusion texture fallback failed: {_diff_exc}")

        # -- 8. Save textured GLB (texture embedded, before rigging) ----------
        if textured_glb is not None:
            step_status(name, "Saving textured model (GLB)")
            shutil.copy2(textured_glb, model_dir / f"{name}_textured.glb")

        # -- 9. Auto-rig textured model ------------------------------------
        if auto_rig and textured_glb is not None:
            step_status(name, "Auto-rigging textured model")
            rigged_tex, rigged_tex_fbx, _tex_manifest, rig_tex_msg = autorig_via_blender(
                textured_glb, rig_profile, scripts_dir=scripts, export_fbx=export_fbx,
                rig_anchors=rig_anchors,
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
