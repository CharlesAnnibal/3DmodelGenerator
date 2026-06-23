"""Remove disconnected border bleed from creature reference images.

Some generated/split reference sheets leave a piece of a neighboring view at
the image edge, for example a tail tip from the side view inside back.png. This
script removes foreground components that touch the image border when they are
not connected to the main subject.
"""

from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def _foreground_mask(img: Image.Image, white_threshold: int) -> np.ndarray:
    arr = np.asarray(img.convert("RGBA"))
    rgb = arr[:, :, :3].astype(np.int16)
    alpha = arr[:, :, 3]
    near_white = (
        (rgb[:, :, 0] >= white_threshold)
        & (rgb[:, :, 1] >= white_threshold)
        & (rgb[:, :, 2] >= white_threshold)
    )
    return (alpha > 10) & ~near_white


def _component_from(
    mask: np.ndarray,
    seen: np.ndarray,
    start_y: int,
    start_x: int,
) -> tuple[list[tuple[int, int]], bool]:
    h, w = mask.shape
    q: deque[tuple[int, int]] = deque([(start_y, start_x)])
    seen[start_y, start_x] = True
    pixels: list[tuple[int, int]] = []
    touches_border = False

    while q:
        y, x = q.popleft()
        pixels.append((y, x))
        if y == 0 or x == 0 or y == h - 1 or x == w - 1:
            touches_border = True
        for ny in (y - 1, y, y + 1):
            if ny < 0 or ny >= h:
                continue
            for nx in (x - 1, x, x + 1):
                if nx < 0 or nx >= w or (ny == y and nx == x):
                    continue
                if mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    q.append((ny, nx))

    return pixels, touches_border


def _border_components(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    seen = np.zeros(mask.shape, dtype=bool)
    result: list[list[tuple[int, int]]] = []
    h, w = mask.shape
    starts: list[tuple[int, int]] = []
    for x in range(w):
        starts.append((0, x))
        starts.append((h - 1, x))
    for y in range(1, h - 1):
        starts.append((y, 0))
        starts.append((y, w - 1))
    for y, x in starts:
        if not mask[y, x] or seen[y, x]:
            continue
        pixels, _touches_border = _component_from(mask, seen, y, x)
        result.append(pixels)
    return result


def _largest_component_area(mask: np.ndarray) -> int:
    seen = np.zeros(mask.shape, dtype=bool)
    largest = 0
    ys, xs = np.nonzero(mask)
    for y, x in zip(ys.tolist(), xs.tolist()):
        if seen[y, x]:
            continue
        pixels, _touches_border = _component_from(mask, seen, y, x)
        largest = max(largest, len(pixels))
    return largest


def clean_image(
    path: Path,
    *,
    min_area: int,
    max_main_ratio: float,
    white_threshold: int,
    write: bool,
) -> int:
    img = Image.open(path)
    mask = _foreground_mask(img, white_threshold)
    if not mask.any():
        return 0

    border_comps = _border_components(mask)
    if not border_comps:
        return 0

    # The common case is a split-sheet leftover touching the canvas edge while
    # the actual subject is centered. Only compute a full largest-component
    # pass when a border component is large enough that it might be the subject.
    fg_area = int(mask.sum())
    largest_area = 0
    remove_pixels: list[tuple[int, int]] = []
    for pixels in border_comps:
        area = len(pixels)
        if area < min_area:
            continue
        if area >= fg_area * max_main_ratio:
            if largest_area == 0:
                largest_area = _largest_component_area(mask)
            if area >= largest_area * max_main_ratio:
                continue
        elif area >= fg_area * 0.80:
            continue
        remove_pixels.extend(pixels)

    if not remove_pixels:
        return 0

    if write:
        arr = np.asarray(img.convert("RGBA")).copy()
        ys = [p[0] for p in remove_pixels]
        xs = [p[1] for p in remove_pixels]
        if "A" in img.getbands():
            arr[ys, xs, 3] = 0
            out = Image.fromarray(arr, "RGBA")
        else:
            arr[ys, xs, :3] = 255
            arr[ys, xs, 3] = 255
            out = Image.fromarray(arr, "RGBA").convert(img.mode)
        out.save(path)

    return len(remove_pixels)


def iter_images(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    for path in paths:
        if path.is_dir():
            image_dirs = sorted(p for p in path.glob("*/images") if p.is_dir())
            if image_dirs:
                for image_dir in image_dirs:
                    result.extend(
                        p for p in sorted(image_dir.iterdir())
                        if p.suffix.lower() in IMAGE_EXTS
                    )
            else:
                result.extend(
                    p for p in sorted(path.iterdir()) if p.suffix.lower() in IMAGE_EXTS
                )
        elif path.suffix.lower() in IMAGE_EXTS:
            result.append(path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, default=[Path("models")])
    parser.add_argument("--write", action="store_true", help="Modify files in place.")
    parser.add_argument("--min-area", type=int, default=150)
    parser.add_argument("--max-main-ratio", type=float, default=0.35)
    parser.add_argument("--white-threshold", type=int, default=245)
    args = parser.parse_args()

    changed = 0
    pixels = 0
    for path in iter_images(args.paths):
        removed = clean_image(
            path,
            min_area=args.min_area,
            max_main_ratio=args.max_main_ratio,
            white_threshold=args.white_threshold,
            write=args.write,
        )
        if removed:
            changed += 1
            pixels += removed
            label = "cleaned" if args.write else "would clean"
            print(f"{label}: {path} ({removed} px)")

    action = "Updated" if args.write else "Would update"
    print(f"{action} {changed} image(s), {pixels} pixel(s).")


if __name__ == "__main__":
    main()
