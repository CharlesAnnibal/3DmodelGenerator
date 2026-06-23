"""CLI entry point for the batch model factory."""

from __future__ import annotations

import argparse
import glob
import os
import sys
import warnings
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap sys.path so we can import from the sibling modelGenerator package
# and the Hunyuan third-party tree without requiring an editable install.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
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


def _resolve_target_height(args: argparse.Namespace) -> float | None:
    """Return the target height in metres from CLI flags, or None if not set."""
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
    return None


def _read_creature_config(folder: Path) -> dict:
    """Read config.yaml from a creature folder (checks images/ subdir first)."""
    for config_path in [folder / "images" / "config.yaml", folder / "config.yaml"]:
        if config_path.is_file():
            try:
                import yaml
                with config_path.open("r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                if not isinstance(data, dict):
                    raise SystemExit(f"{config_path}: expected a YAML mapping, got {type(data).__name__}")
                return data
            except ImportError:
                raise SystemExit("config.yaml found but PyYAML is not installed. Run: pip install pyyaml")
    return {}


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

_PARAM_DEFAULTS: dict[str, object] = {
    "preset": "Hunyuan3D-2 (quality)",
    "steps": 40,
    "seed": 12345,
    "texture_size": 2048,
    "rig_profile": "auto",
}

_VALID_CONFIG_KEYS = frozenset({"height", "preset", "steps", "seed", "texture_size", "rig_profile", "rig_anchors"})
_VALID_RIG_PROFILES = frozenset({"auto", "humanoid", "quadruped", "avian", "serpentine"})
_VALID_TEXTURE_SIZES = frozenset({512, 1024, 2048, 4096})


def _resolve_creature_params(args: argparse.Namespace, config: dict) -> dict:
    """Resolve all per-creature pipeline params: CLI flag > config.yaml > default."""
    unknown = set(config) - _VALID_CONFIG_KEYS
    if unknown:
        raise SystemExit(f"config.yaml: unknown key(s): {sorted(unknown)}. "
                         f"Valid keys: {sorted(_VALID_CONFIG_KEYS)}")

    def _pick(cli_val, config_key: str):
        if cli_val is not None:
            return cli_val
        if config_key in config:
            return config[config_key]
        return _PARAM_DEFAULTS[config_key]

    preset = _pick(args.preset, "preset")
    if preset not in PRESETS:
        raise SystemExit(f"config.yaml: invalid preset {preset!r}. "
                         f"Valid: {list(PRESETS)}")

    try:
        steps = int(_pick(args.steps, "steps"))
    except (TypeError, ValueError):
        raise SystemExit(f"config.yaml: invalid steps value {config.get('steps')!r}")

    try:
        seed = int(_pick(args.seed, "seed"))
    except (TypeError, ValueError):
        raise SystemExit(f"config.yaml: invalid seed value {config.get('seed')!r}")

    try:
        texture_size = int(_pick(args.texture_size, "texture_size"))
    except (TypeError, ValueError):
        raise SystemExit(f"config.yaml: invalid texture_size value {config.get('texture_size')!r}")
    if texture_size not in _VALID_TEXTURE_SIZES:
        raise SystemExit(f"config.yaml: invalid texture_size {texture_size}. "
                         f"Valid: {sorted(_VALID_TEXTURE_SIZES)}")

    rig_profile = str(_pick(args.rig_profile, "rig_profile"))
    if rig_profile not in _VALID_RIG_PROFILES:
        raise SystemExit(f"config.yaml: invalid rig_profile {rig_profile!r}. "
                         f"Valid: {sorted(_VALID_RIG_PROFILES)}")

    # Height uses the existing resolver that handles presets + floats.
    cli_height = _resolve_target_height(args)
    if cli_height is not None:
        target_height = cli_height
    elif "height" in config:
        v = str(config["height"]).strip().lower()
        if v in _HEIGHT_PRESETS:
            target_height = _HEIGHT_PRESETS[v]
        else:
            try:
                target_height = float(v)
            except ValueError:
                raise SystemExit(
                    f"config.yaml: invalid height value {config['height']!r}. "
                    f"Use a number or one of {list(_HEIGHT_PRESETS)}."
                )
    else:
        target_height = _HEIGHT_PRESETS["medium"]

    rig_anchors = config.get("rig_anchors")
    if rig_anchors is not None and not isinstance(rig_anchors, dict):
        raise SystemExit("config.yaml: rig_anchors must be a mapping of bone name to [x, y, z]")

    return {
        "preset": preset,
        "steps": steps,
        "seed": seed,
        "texture_size": texture_size,
        "rig_profile": rig_profile,
        "target_height": target_height,
        "rig_anchors": rig_anchors,
    }


# View names for mesh generation — orthogonal only, no diagonal views.
_MESH_VIEW_NAMES = ("front", "back", "side", "left", "right")
# All supported view names including diagonal — used for texture baking only.
_VIEW_NAMES = ("front", "back", "side", "left", "right", "three_quarter")
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")

# Glob patterns for intermediate/debug artifacts to remove during clean.
_GARBAGE_PATTERNS = [
    "debug_faceassign.*",
    "gltf_buffer_*.bin",
    "*_data.bin",
    "*_textured_rigged_img*.png",
    "*_textured.gltf",
    "*_textured_rigged.gltf",
    "*_textured.png",
]


def _images_dir(folder: Path) -> Path:
    """Return the images subdirectory if it exists, otherwise the folder itself."""
    images_subdir = folder / "images"
    return images_subdir if images_subdir.is_dir() else folder


def _detect_images(folder: Path) -> dict[str, Path]:
    """Map view name -> image path for mesh generation (orthogonal views only).

    three_quarter is intentionally excluded — diagonal views confuse Hunyuan3D's
    reconstruction which expects canonical orthogonal camera angles.
    """
    search_dir = _images_dir(folder)
    images: dict[str, Path] = {}
    for view in _MESH_VIEW_NAMES:
        for ext in _IMAGE_EXTS:
            candidate = search_dir / f"{view}{ext}"
            if candidate.is_file():
                images[view] = candidate
                break
    if images:
        return images
    # Fall back to partial-name matching (e.g. front_processed.png, back_v2.webp)
    for path in search_dir.iterdir():
        if path.suffix.lower() not in _IMAGE_EXTS:
            continue
        stem = path.stem.lower()
        for view in _MESH_VIEW_NAMES:
            if view in stem and view not in images:
                images[view] = path
                break
    return images


def _detect_texture_images(folder: Path) -> dict[str, Path]:
    """Map view name -> image path for texture baking, casting a wider net.

    Matches any image file whose stem *contains* a view keyword
    (e.g. ``front_processed.png``, ``back_v2.webp``).  Used to supply
    extra coverage views for texture baking when shape generation ran in
    single-image mode.
    """
    search_dir = _images_dir(folder)
    found: dict[str, Path] = {}
    for path in search_dir.iterdir():
        if path.suffix.lower() not in _IMAGE_EXTS:
            continue
        stem = path.stem.lower()
        for view in _VIEW_NAMES:
            if view in stem and view not in found:
                found[view] = path
                break
    return found


def _mark_images_processed(creature_name: str, images: dict[str, Path]) -> None:
    """Rename source images with '_processed' suffix to prevent accidental re-runs.

    Uses ``os.replace`` first. On ``OSError`` (e.g. WinError 1392 "corrupted and
    unreadable" from a flaky volume or cloud sync), falls back to copy + delete.
    Failures are logged but do not fail the run — the bake has already completed.
    """
    import os
    import shutil

    from model_generator_cli.progress import warn

    for _view_name, image_path in images.items():
        if not image_path.is_file():
            continue
        stem = image_path.stem
        suffix = image_path.suffix
        while stem.endswith("_processed"):
            stem = stem[: -len("_processed")]
        processed_name = f"{stem}_processed{suffix}"
        processed_path = image_path.parent / processed_name
        if image_path.resolve() == processed_path.resolve():
            continue
        try:
            os.replace(str(image_path), str(processed_path))
        except OSError as exc:
            try:
                shutil.copy2(image_path, processed_path)
                image_path.unlink(missing_ok=True)
            except OSError as exc2:
                warn(
                    creature_name,
                    f"Could not rename {image_path.name} -> {processed_path.name} "
                    f"({exc}; fallback {exc2}). "
                    "WinError 1392 often means disk/cloud sync issues — run chkdsk on "
                    "the drive or restore the file from backup; pipeline outputs may "
                    "already be under 3dmodel/ and textures/.",
                )


def _scan_creatures(models_dir: Path, only: str | None) -> list[Path]:
    """Return sorted list of creature subdirectories."""
    if not models_dir.is_dir():
        return []
    dirs = sorted(p for p in models_dir.iterdir() if p.is_dir())
    if only is not None:
        dirs = [p for p in dirs if p.name == only]
    return dirs


def _clean_creature(folder: Path, dry_run: bool) -> int:
    """Delete intermediate/debug artifacts from a creature's 3dmodel directory.

    Returns the number of files removed (or that would be removed in dry-run).
    """
    model_dir = folder / "3dmodel"
    if not model_dir.is_dir():
        return 0

    removed = 0
    for pattern in _GARBAGE_PATTERNS:
        for match in glob.glob(str(model_dir / pattern)):
            path = Path(match)
            if dry_run:
                print(f"  [dry-run] would delete: {path}")
            else:
                path.unlink()
                print(f"  deleted: {path}")
            removed += 1
    return removed


def _add_run_args(parser: argparse.ArgumentParser) -> None:
    """Add all `run` subcommand arguments to *parser*."""
    parser.add_argument(
        "--models-dir", type=Path, default=Path("./models"),
        help="Root directory containing creature subfolders (default: ./models).",
    )
    # Deprecated legacy flags — kept for backwards compatibility.
    parser.add_argument(
        "--input-dir", type=Path, default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--preset", default=None, choices=list(PRESETS))
    parser.add_argument("--steps", type=int, default=None)
    parser.add_argument("--octree-resolution", type=int, default=260)
    parser.add_argument("--num-chunks", type=int, default=20000)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument(
        "--texture-size",
        type=int,
        default=None,
        choices=[512, 1024, 2048, 4096],
        help="Albedo texture resolution. Must be a power of two. Default: 2048.",
    )
    parser.add_argument(
        "--rig-profile",
        default=None,
        choices=["auto", "humanoid", "quadruped", "avian", "serpentine"],
    )
    parser.add_argument("--no-rembg", action="store_true")
    parser.add_argument("--no-texture", action="store_true")
    parser.add_argument("--no-fix-legs", action="store_true")
    parser.add_argument("--no-fix-arms", action="store_true",
                        help="Skip the arm depth-fix step (merged/flat arm correction).")
    parser.add_argument("--no-rig", action="store_true")
    parser.add_argument("--no-fbx", action="store_true",
                        help="Skip FBX export (omits *_rigged.fbx and *_textured_rigged.fbx).")
    parser.add_argument("--no-acceptance", action="store_true",
                        help="Skip the acceptance test checks after generation.")
    parser.add_argument("--retexture-only", action="store_true",
                        help="Skip shape generation; rebake texture on the existing model.")
    parser.add_argument(
        "--texture-mode",
        default="cylindrical",
        choices=["cylindrical", "triplanar", "triplanar_blend", "vertex"],
        help="Texture bake algorithm. Default: cylindrical.",
    )
    parser.add_argument(
        "--no-blender-uv-unwrap",
        action="store_true",
        help=(
            "Skip headless Blender Smart UV unwrap before cylindrical texture bake "
            "(use legacy procedural cylindrical UV instead)."
        ),
    )
    parser.add_argument(
        "--no-texture-overlap-repair",
        action="store_true",
        help=(
            "Skip post-bake atlas smoothing (blends mid-sheet overlap bands from "
            "triplanar/cylindrical projection)."
        ),
    )
    parser.add_argument(
        "--no-semantic-texture",
        action="store_true",
        help=(
            "Skip controlled UV-lookup semantic painting and use the projection "
            "texture bake directly."
        ),
    )
    parser.add_argument("--strict", action="store_true",
                        help="Treat acceptance failures as hard errors (creature counts as failed).")
    parser.add_argument("--small",  action="store_true", help="Target height 0.3 m (~cat-sized).")
    parser.add_argument("--medium", action="store_true", help="Target height 1.0 m (default).")
    parser.add_argument("--big",    action="store_true", help="Target height 2.5 m (~bear-sized).")
    parser.add_argument("--huge",   action="store_true", help="Target height 5.0 m (boss/giant).")
    parser.add_argument(
        "--height",
        default=None,
        help="Target height in metres or preset name (small/medium/big/huge).",
    )
    parser.add_argument(
        "--creature",
        default=None,
        help="Process only this creature (subfolder name).",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="model-factory",
        description="Batch 3D model generator.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run",
        help="Run the generation pipeline on creature folders.",
    )
    _add_run_args(run_parser)

    clean_parser = subparsers.add_parser(
        "clean",
        help="Remove intermediate/debug artifacts from creature folders.",
    )
    clean_parser.add_argument(
        "--models-dir", type=Path, default=Path("./models"),
        help="Root directory containing creature subfolders (default: ./models).",
    )
    clean_parser.add_argument(
        "--creature", default=None,
        help="Clean only this creature (subfolder name).",
    )
    clean_parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be deleted without removing anything.",
    )

    return parser.parse_args(argv)


def _cmd_run(args: argparse.Namespace) -> None:
    import time as _time
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

    # Legacy flag support.
    if args.input_dir is not None or args.output_dir is not None:
        warnings.warn(
            "--input-dir/--output-dir are deprecated; use --models-dir instead.",
            DeprecationWarning,
            stacklevel=2,
        )

    models_dir: Path = args.models_dir.resolve()
    models_dir.mkdir(parents=True, exist_ok=True)

    creatures = _scan_creatures(models_dir, args.creature)
    header(f"Model Factory — {len(creatures)} creature(s) found in {models_dir}")

    succeeded = 0
    failed = 0
    skipped = 0

    _run_start = _time.time()

    bar = creature_bar(len(creatures))
    for folder in creatures:
        name = folder.name
        images = _detect_images(folder)

        if not images:
            warn(name, "Empty folder, skipping.")
            skipped += 1
            bar.update(1)
            continue

        config = _read_creature_config(folder)
        params = _resolve_creature_params(args, config)
        texture_imgs = _detect_texture_images(folder)
        begin_creature(name)
        _creature_start = _time.time()
        try:
            process_creature(
                name,
                images,
                models_dir,
                preset=params["preset"],
                steps=params["steps"],
                octree_resolution=args.octree_resolution,
                num_chunks=args.num_chunks,
                seed=params["seed"],
                texture_size=params["texture_size"],
                rig_profile=params["rig_profile"],
                use_rembg=not args.no_rembg,
                with_texture=not args.no_texture,
                fix_legs=not args.no_fix_legs,
                fix_arms=not args.no_fix_arms,
                auto_rig=not args.no_rig,
                target_height=params["target_height"],
                run_acceptance=not args.no_acceptance,
                strict_acceptance=args.strict,
                export_fbx=not args.no_fbx,
                texture_images=texture_imgs if texture_imgs else None,
                retexture_only=args.retexture_only,
                texture_mode=args.texture_mode,
                texture_overlap_repair=not args.no_texture_overlap_repair,
                blender_uv_unwrap=not args.no_blender_uv_unwrap,
                controlled_semantic_texture=not args.no_semantic_texture,
                rig_anchors=params["rig_anchors"],
            )
            _mark_images_processed(name, images)
            _elapsed = _time.time() - _creature_start
            success(name, f"Done — {_elapsed:.0f}s")
            succeeded += 1
        except Exception as exc:
            _elapsed = _time.time() - _creature_start
            error(name, f"{exc} ({_elapsed:.0f}s)")
            failed += 1
        finally:
            end_creature()

        bar.update(1)

    bar.close()
    _total = _time.time() - _run_start
    _m, _s = divmod(int(_total), 60)
    header(
        f"Finished — {succeeded} succeeded, {failed} failed, {skipped} skipped"
        f"  [{_m}m {_s:02d}s total]"
    )


def _cmd_clean(args: argparse.Namespace) -> None:
    models_dir: Path = args.models_dir.resolve()
    creatures = _scan_creatures(models_dir, args.creature)

    if not creatures:
        print(f"No creature folders found in {models_dir}")
        return

    label = "[dry-run] " if args.dry_run else ""
    total = 0
    for folder in creatures:
        count = _clean_creature(folder, args.dry_run)
        if count:
            print(f"{label}{folder.name}: {count} file(s) removed")
        else:
            print(f"{folder.name}: nothing to clean")
        total += count

    print(f"\n{label}Total: {total} file(s) removed across {len(creatures)} creature(s)")


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.command == "run":
        _cmd_run(args)
    elif args.command == "clean":
        _cmd_clean(args)


if __name__ == "__main__":
    main()
