"""Texture generation and fallback-area enhancement via a local diffusion model.

Active model: Nazzaroth2/texture-hell
  - SD2.1 768 fine-tune on 350 PolyHaven albedo textures
  - Prompt format: "texture, <material>, ..." (trigger token: "texture")
  - Loaded via from_single_file() (single .safetensors checkpoint)
  - Override with env var TEXTURE_DIFFUSION_MODEL=<path>

Two integration points in pipeline.py:
  1. Post-bake enhancement — fill neutral-tan fallback areas with generated texture.
  2. Last-resort fallback — generate a full texture when the bake script fails.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image as PILImage

# Primary: Nazzaroth2/texture-hell (.safetensors, SD2.1 768).
# Fallback: dream-textures/texture-diffusion (diffusers dir, SD2 base) — used when
# texture-hell fails to load (from_single_file requires gated HF auth for its config).
_TEXTURE_HELL_PATH = str(
    Path(__file__).resolve().parents[3] / "texture-hell" / "texture-hell_v1.0.safetensors"
)
_TEXTURE_DIFFUSION_PATH = str(
    Path(__file__).resolve().parents[3] / "texture-diffusion"
)
_DEFAULT_MODEL_PATH = (
    _TEXTURE_HELL_PATH if Path(_TEXTURE_HELL_PATH).exists() else _TEXTURE_DIFFUSION_PATH
)
TEXTURE_DIFFUSION_PATH: str = os.environ.get(
    "TEXTURE_DIFFUSION_MODEL", _DEFAULT_MODEL_PATH
)

_pipe_cache: dict[str, object] = {}


def _load_pipe(model_path: str):
    """Lazy-load (and cache) the StableDiffusionPipeline.

    Tries from_single_file for .safetensors checkpoints.  If that fails (e.g.
    HuggingFace gated-repo 404 for the config), automatically falls back to
    the local texture-diffusion diffusers directory which loads fully offline.
    """
    if model_path not in _pipe_cache:
        import torch
        from diffusers import StableDiffusionPipeline

        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        pipe = None

        if model_path.endswith(".safetensors") or model_path.endswith(".ckpt"):
            _yaml = Path(model_path).parent / "v2-inference-v.yaml"
            _yaml_arg = str(_yaml) if _yaml.exists() else None
            try:
                pipe = StableDiffusionPipeline.from_single_file(
                    model_path,
                    original_config_file=_yaml_arg,
                    torch_dtype=dtype,
                )
            except Exception:
                # from_single_file requires network access to a gated HF repo —
                # fall back to texture-diffusion which loads fully offline.
                pipe = None

        if pipe is None:
            fallback = _TEXTURE_DIFFUSION_PATH
            pipe = StableDiffusionPipeline.from_pretrained(fallback, torch_dtype=dtype)

        pipe = pipe.to("cuda" if torch.cuda.is_available() else "cpu")
        pipe.set_progress_bar_config(disable=True)
        _pipe_cache[model_path] = pipe
    return _pipe_cache[model_path]


def _prompt_for(creature_name: str, model_path: str) -> str:
    """Build the correct prompt for whichever model is active."""
    safe = creature_name.lower().replace("_", " ").replace("-", " ")
    if "texture-hell" in model_path:
        return f"texture, matte plastic, miniature figurine, {safe}, seamless, flat lighting, no shadows"
    return f"pbr {safe} creature skin texture, seamless, flat lighting, no shadows"


def generate_pbr_texture(
    creature_name: str,
    size: int = 512,
    model_path: str | None = None,
) -> PILImage.Image:
    """Generate an albedo texture for *creature_name*."""
    if model_path is None:
        model_path = TEXTURE_DIFFUSION_PATH

    safe_name = creature_name.lower().replace("_", " ").replace("-", " ")
    prompt = _prompt_for(safe_name, model_path)

    pipe = _load_pipe(model_path)
    result: PILImage.Image = pipe(
        prompt=prompt,
        num_inference_steps=50,
        guidance_scale=7.5,
    ).images[0]

    if size != 512:
        result = result.resize((size, size), PILImage.LANCZOS)
    return result


def fallback_coverage(
    texture: PILImage.Image,
    base_color: tuple[float, float, float],
    tolerance: float = 0.08,
) -> float:
    """Return fraction of content pixels that are near *base_color* (fallback fill areas)."""
    arr = np.asarray(texture.convert("RGBA"), dtype=np.float32)
    rgb = arr[:, :, :3] / 255.0
    alpha = arr[:, :, 3] / 255.0
    base = np.array(base_color, dtype=np.float32)
    dist = np.abs(rgb - base).max(axis=2)
    content = alpha > 0.1
    if not content.any():
        return 0.0
    return float(((dist < tolerance) & content).sum()) / float(content.sum())


def enhance_texture(
    texture: PILImage.Image,
    base_color: tuple[float, float, float],
    creature_name: str,
    model_path: str | None = None,
    tolerance: float = 0.08,
    coverage_threshold: float = 0.15,
) -> tuple[PILImage.Image, bool]:
    """Replace fallback-coloured areas with diffusion-generated PBR texture.

    Generates at 512×512 (model native res), upscales to match *texture* size.
    Returns (enhanced_texture, was_enhanced).  Returns the original unchanged
    if fallback coverage is below *coverage_threshold*.
    """
    if model_path is None:
        model_path = TEXTURE_DIFFUSION_PATH

    orig_size = texture.size  # (W, H)
    arr = np.asarray(texture.convert("RGBA"), dtype=np.float32)
    rgb = arr[:, :, :3] / 255.0
    alpha = arr[:, :, 3] / 255.0
    base = np.array(base_color, dtype=np.float32)
    dist = np.abs(rgb - base).max(axis=2)
    content = alpha > 0.1
    fallback_mask = (dist < tolerance) & content

    if not content.any() or (
        float(fallback_mask.sum()) / float(content.sum()) < coverage_threshold
    ):
        return texture, False

    generated = generate_pbr_texture(creature_name, size=512, model_path=model_path)
    if generated.size != orig_size:
        generated = generated.resize(orig_size, PILImage.LANCZOS)

    gen_arr = np.asarray(generated.convert("RGBA"), dtype=np.float32)
    mask_4ch = np.stack([fallback_mask] * 4, axis=2)
    result_arr = np.where(mask_4ch, gen_arr, arr)

    return PILImage.fromarray(result_arr.astype(np.uint8), mode="RGBA"), True


def reembed_texture_in_glb(
    glb_path: str,
    new_texture: PILImage.Image,
    out_path: str,
) -> bool:
    """Swap the embedded albedo texture in a GLB, preserving existing UV coordinates.

    Returns True if the output file was written successfully.
    """
    try:
        import trimesh
        from trimesh.visual.texture import TextureVisuals
        from trimesh.visual.material import PBRMaterial

        scene = trimesh.load(glb_path, process=False)
        new_mat = PBRMaterial(baseColorTexture=new_texture.convert("RGB"))

        geometries = (
            list(scene.geometry.values()) if hasattr(scene, "geometry") else [scene]
        )
        swapped = False
        for geom in geometries:
            vis = getattr(geom, "visual", None)
            if vis is not None and hasattr(vis, "uv") and vis.uv is not None:
                geom.visual = TextureVisuals(uv=vis.uv, material=new_mat)
                swapped = True

        if not swapped:
            return False

        scene.export(out_path)
        return Path(out_path).is_file() and Path(out_path).stat().st_size > 0
    except Exception:
        return False
