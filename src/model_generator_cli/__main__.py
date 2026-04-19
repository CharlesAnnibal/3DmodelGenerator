"""CLI entry point for the batch model factory."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap sys.path so we can import from the sibling modelGenerator package
# and the Hunyuan third-party tree without requiring an editable install.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_MG_SRC = _PROJECT_ROOT / "modelGenerator" / "src"
_HUNYUAN_ROOT = _PROJECT_ROOT / "modelGenerator" / "third_party" / "Hunyuan3D-2"

for _p in (_MG_SRC, _HUNYUAN_ROOT):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

_HEIGHT_PRESETS: dict[str, float] = {
    "small":  0.3,
    "medium": 1.0,
    "big":    2.5,
    "huge":   5.0,
}


def _resolve_target_height(args: argparse.Namespace) -> float:
    """Return the target height in metres from CLI flags."""
    if args.height is not None:
        v = args.height.strip().lower()
        if v in _HEIGHT_PRESETS:
            return _HEIGHT_PRESETS[v]
        try:
            return float(v)
        except ValueError:
            raise SystemExit(
                f"--height: invalid value {args.height!r}. "
                f"Use a number or one of {list(_HEIGHT_PRESETS)}."
            )
    if args.huge:
        return _HEIGHT_PRESETS["huge"]
    if args.big:
        return _HEIGHT_PRESETS["big"]
    if args.small:
        return _HEIGHT_PRESETS["small"]
    return _HEIGHT_PRESETS["medium"]


PRESETS: dict[str, dict[str, object]] = {
    "Hunyuan3D-2 (quality)": {
        "steps": 20,
        "octree_resolution": 128,
        "num_chunks": 8000,
    },
    "Hunyuan3D-2 Turbo (faster)": {
        "steps": 10,
        "octree_resolution": 128,
        "num_chunks": 8000,
    },
    "Hunyuan3D-2mini (low VRAM)": {
        "steps": 15,
        "octree_resolution": 128,
        "num_chunks": 8000,
    },
}

# Supported reference-image view names and file extensions.
_VIEW_NAMES = ("front", "back", "side", "left", "right")
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="model-factory",
        description="Batch 3D model generator — scans an input directory of creature "
        "folders and runs the Hunyuan3D-2 pipeline on each.",
    )
    parser.add_argument("--input-dir", type=Path, default=Path("./input"))
    parser.add_argument("--output-dir", type=Path, default=Path("./output"))
    parser.add_argument(
        "--preset",
        default="Hunyuan3D-2 (quality)",
        choices=list(PRESETS),
    )
    parser.add_argument("--steps", type=int, default=40)
    parser.add_argument("--octree-resolution", type=int, default=260)
    parser.add_argument("--num-chunks", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument(
        "--texture-size",
        type=int,
        default=2048,
        choices=[512, 1024, 2048, 4096],
        help="Albedo texture resolution. Must be a power of two. Default: 2048.",
    )
    parser.add_argument(
        "--rig-profile",
        default="auto",
        choices=["auto", "humanoid", "quadruped", "serpentine"],
    )
    parser.add_argument("--no-rembg", action="store_true")
    parser.add_argument("--no-texture", action="store_true")
    parser.add_argument("--no-fix-legs", action="store_true")
    parser.add_argument("--no-rig", action="store_true")
    parser.add_argument("--no-fbx", action="store_true",
                        help="Skip FBX export (omits *_rigged.fbx and *_textured_rigged.fbx).")
    parser.add_argument("--no-acceptance", action="store_true",
                        help="Skip the acceptance test checks after generation.")
    parser.add_argument("--strict", action="store_true",
                        help="Treat acceptance failures as hard errors (creature counts as failed).")
    # Size flags — mutually exclusive shorthands; --height overrides all.
    parser.add_argument("--small",  action="store_true", help="Target height 0.3 m (~cat-sized).")
    parser.add_argument("--medium", action="store_true", help="Target height 1.0 m (default).")
    parser.add_argument("--big",    action="store_true", help="Target height 2.5 m (~bear-sized).")
    parser.add_argument("--huge",   action="store_true", help="Target height 5.0 m (boss/giant).")
    parser.add_argument(
        "--height",
        default=None,
        help="Target height in metres or preset name (small/medium/big/huge). "
             "Overrides --small/--medium/--big/--huge when both are given.",
    )
    parser.add_argument(
        "--creature",
        default=None,
        help="Process only this creature (subfolder name).",
    )
    return parser.parse_args(argv)


def _scan_creatures(input_dir: Path, only: str | None) -> list[Path]:
    """Return sorted list of creature subdirectories."""
    if not input_dir.is_dir():
        return []
    dirs = sorted(p for p in input_dir.iterdir() if p.is_dir())
    if only is not None:
        dirs = [p for p in dirs if p.name == only]
    return dirs


def _detect_images(folder: Path) -> dict[str, Path]:
    """Map view name -> image path for recognised reference views."""
    images: dict[str, Path] = {}
    for view in _VIEW_NAMES:
        for ext in _IMAGE_EXTS:
            candidate = folder / f"{view}{ext}"
            if candidate.is_file():
                images[view] = candidate
                break
    return images


def _mark_images_processed(images: dict[str, Path]) -> None:
    """Rename source images with '_processed' suffix to prevent accidental re-runs."""
    for view_name, image_path in images.items():
        if image_path.is_file():
            stem = image_path.stem
            suffix = image_path.suffix
            processed_name = f"{stem}_processed{suffix}"
            processed_path = image_path.parent / processed_name
            image_path.rename(processed_path)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    from model_generator_cli.progress import (
        begin_creature,
        creature_bar,
        end_creature,
        error,
        header,
        success,
        warn,
    )
    from model_generator_cli.pipeline import process_creature

    input_dir: Path = args.input_dir.resolve()
    output_dir: Path = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    creatures = _scan_creatures(input_dir, args.creature)
    header(f"Model Factory — {len(creatures)} creature(s) found in {input_dir}")

    succeeded = 0
    failed = 0
    skipped = 0

    bar = creature_bar(len(creatures))
    for folder in creatures:
        name = folder.name
        images = _detect_images(folder)

        if not images:
            warn(name, "Empty folder, skipping.")
            skipped += 1
            bar.update(1)
            continue

        begin_creature(name)
        try:
            process_creature(
                name,
                images,
                output_dir,
                preset=args.preset,
                steps=args.steps,
                octree_resolution=args.octree_resolution,
                num_chunks=args.num_chunks,
                seed=args.seed,
                texture_size=args.texture_size,
                rig_profile=args.rig_profile,
                use_rembg=not args.no_rembg,
                with_texture=not args.no_texture,
                fix_legs=not args.no_fix_legs,
                auto_rig=not args.no_rig,
                target_height=_resolve_target_height(args),
                run_acceptance=not args.no_acceptance,
                strict_acceptance=args.strict,
                export_fbx=not args.no_fbx,
            )
            _mark_images_processed(images)
            success(name, "Done")
            succeeded += 1
        except Exception as exc:
            error(name, str(exc))
            failed += 1
        finally:
            end_creature()

        bar.update(1)

    bar.close()

    header(
        f"Finished — {succeeded} succeeded, {failed} failed, {skipped} skipped"
    )


if __name__ == "__main__":
    main()
