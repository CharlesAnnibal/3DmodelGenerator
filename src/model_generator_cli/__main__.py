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
    """Read config.yaml from a creature folder, returning an empty dict if absent."""
    config_path = folder / "config.yaml"
    if not config_path.is_file():
        return {}
    try:
        import yaml
        with config_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise SystemExit(f"{config_path}: expected a YAML mapping, got {type(data).__name__}")
        return data
    except ImportError:
        raise SystemExit("config.yaml found but PyYAML is not installed. Run: pip install pyyaml")


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

_VALID_CONFIG_KEYS = frozenset({"height", "preset", "steps", "seed", "texture_size", "rig_profile"})
_VALID_RIG_PROFILES = frozenset({"auto", "humanoid", "quadruped", "serpentine"})
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

    return {
        "preset": preset,
        "steps": steps,
        "seed": seed,
        "texture_size": texture_size,
        "rig_profile": rig_profile,
        "target_height": target_height,
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
        default=None,
        choices=list(PRESETS),
    )
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


def _detect_texture_images(folder: Path) -> dict[str, Path]:
    """Map view name -> image path for texture baking, casting a wider net.

    Matches any image file whose stem *contains* a view keyword
    (e.g. ``front_processed.png``, ``back_v2.webp``).  Used to supply
    extra coverage views for texture baking when shape generation ran in
    single-image mode.
    """
    found: dict[str, Path] = {}
    for path in folder.iterdir():
        if path.suffix.lower() not in _IMAGE_EXTS:
            continue
        stem = path.stem.lower()
        for view in _VIEW_NAMES:
            if view in stem and view not in found:
                found[view] = path
                break
    return found


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

        config = _read_creature_config(folder)
        params = _resolve_creature_params(args, config)
        texture_imgs = _detect_texture_images(folder)
        begin_creature(name)
        try:
            process_creature(
                name,
                images,
                output_dir,
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
                auto_rig=not args.no_rig,
                target_height=params["target_height"],
                run_acceptance=not args.no_acceptance,
                strict_acceptance=args.strict,
                export_fbx=not args.no_fbx,
                texture_images=texture_imgs if texture_imgs else None,
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
