"""One-time migration: collapse input/ + output/ into models/.

Usage:
    python scripts/migrate_to_models_dir.py [--dry-run] [--input-dir PATH] [--output-dir PATH] [--models-dir PATH]

Each creature gets a single folder under models/:
    models/{creature}/images/   ← reference images (was input/{creature}/)
    models/{creature}/3dmodel/  ← generated models (was output/{creature}/3dmodel/)
    models/{creature}/textures/ ← baked textures
    models/{creature}/renders/  ← render images
    models/{creature}/acceptance.json
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-dir", type=Path, default=Path("./input"))
    parser.add_argument("--output-dir", type=Path, default=Path("./output"))
    parser.add_argument("--models-dir", type=Path, default=Path("./models"))
    parser.add_argument("--dry-run", action="store_true", help="Print what would happen without touching files.")
    return parser.parse_args()


def _move(src: Path, dst: Path, dry_run: bool) -> None:
    if dry_run:
        print(f"  [dry-run] move {src} -> {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    print(f"  moved {src} -> {dst}")


def _migrate_input(input_dir: Path, models_dir: Path, dry_run: bool) -> list[str]:
    """Move input/{creature}/* -> models/{creature}/images/."""
    migrated = []
    if not input_dir.is_dir():
        print(f"[input] {input_dir} not found, skipping.")
        return migrated

    for creature_dir in sorted(input_dir.iterdir()):
        if not creature_dir.is_dir():
            continue
        name = creature_dir.name
        images_dst = models_dir / name / "images"

        if (models_dir / name / "images").is_dir():
            print(f"[input] {name}: images/ already exists in models/, skipping.")
            continue

        print(f"[input] {name}: moving reference images -> models/{name}/images/")
        if not dry_run:
            images_dst.mkdir(parents=True, exist_ok=True)

        for item in sorted(creature_dir.iterdir()):
            _move(item, images_dst / item.name, dry_run)

        migrated.append(name)

    return migrated


def _migrate_output(output_dir: Path, models_dir: Path, dry_run: bool) -> list[str]:
    """Move output/{creature}/* -> models/{creature}/."""
    migrated = []
    if not output_dir.is_dir():
        print(f"[output] {output_dir} not found, skipping.")
        return migrated

    for creature_dir in sorted(output_dir.iterdir()):
        if not creature_dir.is_dir():
            continue
        name = creature_dir.name
        dst_root = models_dir / name

        # Move each known subdirectory and loose file.
        for item in sorted(creature_dir.iterdir()):
            dst = dst_root / item.name
            if dst.exists():
                print(f"[output] {name}/{item.name}: already exists in models/, skipping.")
                continue
            print(f"[output] {name}: moving {item.name} -> models/{name}/{item.name}")
            _move(item, dst, dry_run)

        migrated.append(name)

    return migrated


def _try_remove_empty(directory: Path, dry_run: bool) -> None:
    if not directory.is_dir():
        return
    remaining = list(directory.iterdir())
    if remaining:
        print(f"[cleanup] {directory} still has {len(remaining)} item(s) — not removing.")
        return
    if dry_run:
        print(f"  [dry-run] would remove empty directory {directory}")
    else:
        directory.rmdir()
        print(f"  removed empty directory {directory}")


def main() -> None:
    args = _parse_args()
    root = Path(".").resolve()
    input_dir = args.input_dir if args.input_dir.is_absolute() else (root / args.input_dir)
    output_dir = args.output_dir if args.output_dir.is_absolute() else (root / args.output_dir)
    models_dir = args.models_dir if args.models_dir.is_absolute() else (root / args.models_dir)

    if args.dry_run:
        print("=== DRY RUN — no files will be touched ===\n")

    if not args.dry_run:
        models_dir.mkdir(parents=True, exist_ok=True)

    migrated_input = _migrate_input(input_dir, models_dir, args.dry_run)
    migrated_output = _migrate_output(output_dir, models_dir, args.dry_run)

    print()
    _try_remove_empty(input_dir, args.dry_run)
    _try_remove_empty(output_dir, args.dry_run)

    print(f"\nDone. {len(migrated_input)} creature(s) migrated from input/, "
          f"{len(migrated_output)} from output/.")

    if args.dry_run:
        print("\nRe-run without --dry-run to apply changes.")


if __name__ == "__main__":
    main()
