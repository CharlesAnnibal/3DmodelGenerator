"""
synthesize_front_view.py — Approximate front view from a 3/4 reference image.

Takes a 3/4-angle illustration and applies a perspective de-rotation so that
Hunyuan3D can receive a second camera angle that shows lateral separation
between limbs that overlap in the 3/4 view.

The warp is intentionally approximate: the goal is not photographic accuracy
but giving the shape-generation model a second viewpoint hint that shows both
arms at visually distinct horizontal positions.

Approach
--------
1. Strip white background (white -> transparent).
2. Fit a bounding box to the opaque pixels to find the creature extent.
3. Apply a horizontal perspective shear: the 3/4 angle (typically ~45 deg from
   front) is countered by stretching the near side and compressing the far side,
   simulating a frontal rotation.
4. Optionally mirror one side to increase bilateral symmetry.
5. White-fill the background and save.

Usage
-----
python synthesize_front_view.py input_three_quarter.png output_front.png [--az DEG]

Options
-------
  --az DEG     Camera azimuth of the input image in degrees from front (default 45).
               The warp counter-rotates by this angle.
  --no-mirror  Skip the bilateral symmetry step (default: mirror right half from left).
  --pad FRAC   Padding around cropped creature as fraction of extent (default 0.05).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps


# ---------------------------------------------------------------------------
# Background helpers
# ---------------------------------------------------------------------------

def _strip_white_bg(img: Image.Image, threshold: int = 230) -> Image.Image:
    arr = np.array(img.convert("RGBA"))
    r, g, b = arr[:, :, 0].astype(int), arr[:, :, 1].astype(int), arr[:, :, 2].astype(int)
    mask = (r >= threshold) & (g >= threshold) & (b >= threshold)
    arr[mask, 3] = 0
    return Image.fromarray(arr, "RGBA")


def _crop_to_content(img: Image.Image, padding: float = 0.05) -> tuple[Image.Image, tuple[int,int,int,int]]:
    arr = np.array(img.convert("RGBA"))
    alpha = arr[:, :, 3]
    rows = np.any(alpha > 10, axis=1)
    cols = np.any(alpha > 10, axis=0)
    if not rows.any() or not cols.any():
        return img, (0, 0, img.width, img.height)
    r0, r1 = int(np.where(rows)[0][0]), int(np.where(rows)[0][-1])
    c0, c1 = int(np.where(cols)[0][0]), int(np.where(cols)[0][-1])
    H, W = arr.shape[:2]
    pr = max(1, int(padding * (r1 - r0)))
    pc = max(1, int(padding * (c1 - c0)))
    r0, r1 = max(0, r0 - pr), min(H - 1, r1 + pr)
    c0, c1 = max(0, c0 - pc), min(W - 1, c1 + pc)
    return img.crop((c0, r0, c1 + 1, r1 + 1)), (c0, r0, c1 + 1, r1 + 1)


# ---------------------------------------------------------------------------
# Perspective warp helpers (pure PIL)
# ---------------------------------------------------------------------------

def _perspective_shear(img: Image.Image, az_deg: float) -> Image.Image:
    """Apply horizontal de-rotation shear to approximate a front view.

    For a 3/4 image at azimuth *az_deg* degrees, we want to counter-rotate
    by applying a horizontal stretch on the side facing the camera.

    Strategy: split the image at its horizontal midpoint.  The left half
    (near side in a right-facing pose) is stretched, the right half is
    compressed.  The stretch factor is 1/cos(az_deg).

    This is a crude but effective approximation that makes the two sides of
    the creature appear at more symmetrical horizontal positions.
    """
    az = np.radians(min(max(az_deg, 5), 75))
    stretch = 1.0 / np.cos(az)   # > 1

    W, H = img.size
    mid = W // 2

    left_half = img.crop((0, 0, mid, H))
    right_half = img.crop((mid, 0, W, H))

    new_left_w = max(1, int(mid * stretch))
    new_right_w = max(1, int((W - mid) / stretch))

    left_resized = left_half.resize((new_left_w, H), Image.LANCZOS)
    right_resized = right_half.resize((new_right_w, H), Image.LANCZOS)

    new_w = new_left_w + new_right_w
    out = Image.new("RGBA", (new_w, H), (255, 255, 255, 0))
    out.paste(left_resized, (0, 0))
    out.paste(right_resized, (new_left_w, 0))
    return out


# ---------------------------------------------------------------------------
# Main synthesis
# ---------------------------------------------------------------------------

def synthesize_front_view(
    input_path: str,
    output_path: str,
    az_deg: float = 45.0,
    mirror: bool = True,
    pad: float = 0.05,
) -> str:
    img = Image.open(input_path).convert("RGBA")
    W0, H0 = img.size

    # 1. Strip background
    img = _strip_white_bg(img)

    # 2. Crop tight
    img, bbox = _crop_to_content(img, padding=pad)
    print(f"[synth] Cropped: {img.size}  (from {W0}x{H0}, bbox={bbox})")

    # 3. Horizontal perspective de-rotation
    img = _perspective_shear(img, az_deg)
    print(f"[synth] After shear: {img.size}")

    # 4. Optional bilateral mirror: take left half, mirror to right
    if mirror:
        W, H = img.size
        left = img.crop((0, 0, W // 2, H))
        right_mirror = ImageOps.mirror(left)
        mirrored = Image.new("RGBA", (W, H), (255, 255, 255, 0))
        mirrored.paste(left, (0, 0))
        mirrored.paste(right_mirror, (W // 2, 0))
        img = mirrored
        print(f"[synth] Mirrored right half from left")

    # 5. White background
    out = Image.new("RGBA", img.size, (255, 255, 255, 255))
    out.paste(img, mask=img.split()[3])
    out = out.convert("RGB")

    # 6. Resize to match original height (keep proportional)
    out = out.resize((W0, H0), Image.LANCZOS)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    out.save(output_path)
    print(f"[synth] Saved: {output_path}  ({out.size})")
    return f"Done. Saved synthetic front view -> {output_path}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Synthesize approx front view from 3/4 image.")
    p.add_argument("input",  help="Input 3/4 image (PNG/JPG).")
    p.add_argument("output", help="Output front-view PNG path.")
    p.add_argument("--az",     type=float, default=45.0,
                   help="Azimuth of input image from front in degrees (default 45).")
    p.add_argument("--no-mirror", action="store_true",
                   help="Skip bilateral mirror step.")
    p.add_argument("--pad",   type=float, default=0.05,
                   help="Crop padding fraction (default 0.05).")
    args = p.parse_args()
    result = synthesize_front_view(
        args.input, args.output,
        az_deg=args.az,
        mirror=not args.no_mirror,
        pad=args.pad,
    )
    print(f"[synth] {result}")


if __name__ == "__main__":
    main()
