"""Soften triplanar/cylindrical overlap bands in baked albedo atlases.

Projective baking often leaves horizontal smears and duplicate features in the
middle of the UV sheet.  This step blends a Gaussian-blurred copy into a
vertical band (with edge taper) so detail at the top/bottom of the atlas is
preserved.  Same idea as ``texturePainter/scripts/smooth_atlas_band.py``;
this module is the canonical copy used by the CLI pipeline.
"""

from __future__ import annotations

from PIL import Image as PILImage
from PIL import ImageFilter


def repair_triplanar_overlap(
    texture: PILImage.Image,
    *,
    blur_radius: float = 16.0,
    band_center: float = 0.48,
    band_sigma: float = 0.14,
    strength: float = 0.62,
    edge_taper: float = 0.08,
) -> PILImage.Image:
    """Return a repaired RGB/RGBA PIL image (same mode as input, size unchanged)."""
    import numpy as np

    src = texture.convert("RGBA")
    arr = np.asarray(src, dtype=np.float32)
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3:4]
    h, w = rgb.shape[0], rgb.shape[1]

    im_rgb = PILImage.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), mode="RGB")
    blur = im_rgb.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    barr = np.asarray(blur, dtype=np.float32)

    yy = np.linspace(0.0, 1.0, h, dtype=np.float32)
    band = np.exp(-((yy - band_center) ** 2) / (2 * band_sigma**2))
    edge = np.ones(h, dtype=np.float32)
    for i in range(h):
        yp = float(yy[i])
        if yp < edge_taper:
            edge[i] = yp / edge_taper
        elif yp > 1.0 - edge_taper:
            edge[i] = (1.0 - yp) / edge_taper
    mask = (strength * band * edge).reshape(h, 1, 1)

    mixed_rgb = rgb * (1.0 - mask) + barr * mask
    out = np.concatenate([mixed_rgb, alpha], axis=2)
    return PILImage.fromarray(np.clip(out, 0, 255).astype(np.uint8), mode="RGBA")
