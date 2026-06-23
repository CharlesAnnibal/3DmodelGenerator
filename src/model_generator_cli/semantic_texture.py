"""Controlled semantic texture generation from final UV lookup renders.

This is intentionally conservative.  It does not project full reference images
into the atlas, because that copies shadows/backgrounds and creates the visual
glitches seen in earlier Pupplynx attempts.  Instead it builds a clean base coat
and transfers only high-confidence features (blue eyes, dark tips/lines, and
brown markings) through the final UV lookup views.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image as PILImage
from PIL import ImageFilter, ImageOps


def _content_crop(img: PILImage.Image) -> PILImage.Image:
    arr = np.asarray(img.convert("RGBA"))
    rgb = arr[:, :, :3].astype(np.int16)
    alpha = arr[:, :, 3]
    near_white = (rgb.min(axis=2) > 232) & ((rgb.max(axis=2) - rgb.min(axis=2)) < 35)
    mask = (alpha > 10) & ~near_white
    if not mask.any():
        return img.convert("RGBA")
    ys, xs = np.where(mask)
    pad_x = max(2, int((xs.max() - xs.min() + 1) * 0.03))
    pad_y = max(2, int((ys.max() - ys.min() + 1) * 0.03))
    box = (
        max(0, int(xs.min()) - pad_x),
        max(0, int(ys.min()) - pad_y),
        min(img.width, int(xs.max()) + 1 + pad_x),
        min(img.height, int(ys.max()) + 1 + pad_y),
    )
    return img.convert("RGBA").crop(box)


def _foreground_alpha(img: PILImage.Image) -> PILImage.Image:
    arr = np.asarray(img.convert("RGBA")).copy()
    rgb = arr[:, :, :3].astype(np.int16)
    near_white = (rgb.min(axis=2) > 232) & ((rgb.max(axis=2) - rgb.min(axis=2)) < 35)
    arr[:, :, 3] = np.where(near_white, 0, arr[:, :, 3])
    alpha = PILImage.fromarray(arr[:, :, 3]).filter(ImageFilter.MinFilter(3))
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.5))
    arr[:, :, 3] = np.asarray(alpha)
    return PILImage.fromarray(arr, "RGBA")


def _align_to_lookup(ref: PILImage.Image, lookup: PILImage.Image) -> PILImage.Image:
    luv = np.asarray(lookup.convert("RGB"))
    visible = (luv[:, :, 0] | luv[:, :, 1] | luv[:, :, 2]) > 2
    ys, xs = np.where(visible)
    canvas = PILImage.new("RGBA", lookup.size, (0, 0, 0, 0))
    if len(xs) == 0:
        return canvas
    ref = _content_crop(_foreground_alpha(ref))
    if ref.width <= 1 or ref.height <= 1:
        return canvas
    lx0, lx1, ly0, ly1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    target_w = max(1, lx1 - lx0)
    target_h = max(1, ly1 - ly0)
    scale = min(target_w / ref.width, target_h / ref.height)
    resized = ref.resize(
        (max(1, int(ref.width * scale)), max(1, int(ref.height * scale))),
        PILImage.LANCZOS,
    )
    x = lx0 + (target_w - resized.width) // 2
    y = ly0 + (target_h - resized.height) // 2
    canvas.alpha_composite(resized, (x, y))
    return canvas


def _component_filter(mask: np.ndarray, min_pixels: int, max_pixels: int) -> np.ndarray:
    try:
        from scipy import ndimage

        labels, n = ndimage.label(mask)
        if n == 0:
            return mask
        sizes = np.bincount(labels.ravel())
        keep = np.zeros(n + 1, dtype=bool)
        keep[(sizes >= min_pixels) & (sizes <= max_pixels)] = True
        keep[0] = False
        return keep[labels]
    except Exception:
        return mask


def _feature_mask(aligned: PILImage.Image, *, view: str) -> np.ndarray:
    arr = np.asarray(aligned.convert("RGBA"), dtype=np.int16)
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3] > 20
    mean = rgb.mean(axis=2)
    spread = rgb.max(axis=2) - rgb.min(axis=2)

    blue = (
        (rgb[:, :, 2] > rgb[:, :, 0] + 30)
        & (rgb[:, :, 1] > rgb[:, :, 0] + 5)
        & (mean > 45)
        & (mean < 205)
        & alpha
    )
    dark = (mean < 82) & (spread < 95) & alpha
    brown = (mean > 82) & (mean < 158) & (spread < 80) & alpha

    h, w = mean.shape
    yy, xx = np.ogrid[:h, :w]
    xn = xx / max(1, w - 1)
    yn = yy / max(1, h - 1)

    if view == "front":
        # Keep eyes, nose/line, ear caps, forehead/cheek stones.  Reject body
        # shadows and background remnants.
        allowed = (
            ((yn > 0.08) & (yn < 0.42) & ((xn < 0.34) | (xn > 0.66)))
            | ((yn > 0.30) & (yn < 0.58) & (xn > 0.24) & (xn < 0.76))
            | ((yn > 0.18) & (yn < 0.36) & (xn > 0.34) & (xn < 0.66))
        )
    elif view in {"left", "right"}:
        allowed = (
            ((yn > 0.06) & (yn < 0.36) & (xn > 0.45) & (xn < 0.75))
            | ((yn > 0.28) & (yn < 0.66) & (xn > 0.28) & (xn < 0.78))
            | ((yn > 0.42) & (yn < 0.62) & (xn < 0.30))
        )
    else:
        allowed = alpha

    mask = (blue | dark | brown) & allowed
    mask = _component_filter(mask, min_pixels=18, max_pixels=9000)
    return mask


def _splat_features(
    texture: np.ndarray,
    weight: np.ndarray,
    lookup: PILImage.Image,
    aligned: PILImage.Image,
    mask: np.ndarray,
    strength: float,
) -> None:
    size = texture.shape[0]
    luv = np.asarray(lookup.convert("RGB"), dtype=np.uint8)
    ref = np.asarray(aligned.convert("RGBA"), dtype=np.float32)
    visible = (luv[:, :, 0] | luv[:, :, 1] | luv[:, :, 2]) > 2
    ys, xs = np.where(mask & visible)
    if len(xs) == 0:
        return
    u = np.clip(np.rint(luv[:, :, 0].astype(np.float32) / 255.0 * (size - 1)).astype(np.int32), 0, size - 1)
    v = np.clip(np.rint(luv[:, :, 1].astype(np.float32) / 255.0 * (size - 1)).astype(np.int32), 0, size - 1)
    alpha = ref[:, :, 3] / 255.0 * strength
    colors = ref[:, :, :3]
    for dy in (-2, -1, 0, 1, 2):
        for dx in (-2, -1, 0, 1, 2):
            k = 1.0 / (1.0 + abs(dx) + abs(dy))
            uu = np.clip(u[ys, xs] + dx, 0, size - 1)
            vv = np.clip(v[ys, xs] + dy, 0, size - 1)
            w = alpha[ys, xs] * k
            for ch in range(3):
                np.add.at(texture[:, :, ch], (vv, uu), colors[ys, xs, ch] * w)
            np.add.at(weight, (vv, uu), w)


def generate_semantic_texture(
    texture_images: dict[str, Path],
    uv_lookup_files: dict[str, str],
    *,
    base_color: tuple[float, float, float],
    texture_size: int,
) -> PILImage.Image:
    """Generate a clean atlas from final UV lookup views and reference images."""
    base = np.array(base_color, dtype=np.float32) * 255.0
    accum = np.zeros((texture_size, texture_size, 3), dtype=np.float32)
    weights = np.zeros((texture_size, texture_size), dtype=np.float32)

    view_sources: list[tuple[str, Path, bool, float]] = []
    if "back" in texture_images and "back" in uv_lookup_files:
        view_sources.append(("back", texture_images["back"], False, 0.45))
    side = texture_images.get("side") or texture_images.get("left") or texture_images.get("right")
    if side is not None:
        if "left" in uv_lookup_files:
            view_sources.append(("left", side, False, 0.55))
        if "right" in uv_lookup_files:
            view_sources.append(("right", side, True, 0.45))
    if "front" in texture_images and "front" in uv_lookup_files:
        view_sources.append(("front", texture_images["front"], False, 0.85))

    for view, ref_path, mirror, strength in view_sources:
        lookup = PILImage.open(uv_lookup_files[view]).convert("RGB")
        ref = PILImage.open(ref_path).convert("RGBA")
        if mirror:
            ref = ImageOps.mirror(ref)
        aligned = _align_to_lookup(ref, lookup)
        mask = _feature_mask(aligned, view=view)
        _splat_features(accum, weights, lookup, aligned, mask, strength)

    result = np.zeros((texture_size, texture_size, 3), dtype=np.float32)
    result[:, :, :] = base.reshape(1, 1, 3)
    painted = weights > 0.01
    result[painted] = accum[painted] / weights[painted, None]

    # Feather sparse transferred features into the base coat.
    img = PILImage.fromarray(np.clip(result, 0, 255).astype(np.uint8), mode="RGB")
    img = img.filter(ImageFilter.GaussianBlur(0.45))
    return img
