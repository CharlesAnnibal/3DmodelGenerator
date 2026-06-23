"""Align generator model folders + asset file names to Aurarena's canonical slugs.

Aurarena (`Assets/3DModels/{N}-{slug}/`) is the source of truth for creature
names. The generator's `models/` still carries original concept names for some
creatures (e.g. 25-electric-guepard vs 25-thundero) and a couple of stale file
prefixes (15-worcomb holds 3-worcomb_* files; 20-coffet holds "20- coffet_*").

This renames, per creature matched by leading number:
  - the folder            models/<old>           -> models/<slug>
  - every 3dmodel/ file    <anyprefix>_textured*  -> <slug>_textured*
                           <anyprefix>_rig_manifest.json -> <slug>_rig_manifest.json
                           raw <anyprefix>.glb    -> <slug>.glb
Concept images (front/back/side/config) carry no creature prefix and are left.

Usage:
  python scripts/align_folder_names.py            # dry run (default)
  python scripts/align_folder_names.py --write
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AURARENA_3DMODELS = Path(r"D:\Projects\Games\Aurarena\Assets\Creatures")

NUM_RE = re.compile(r"^(\d+)-")

# Suffixes that follow the creature prefix in 3dmodel/ filenames.
SUFFIXES = (
    "_textured_rigged.glb",
    "_textured_rigged.fbx",
    "_textured.glb",
    "_rig_manifest.json",
)


def _num(name: str) -> str | None:
    m = NUM_RE.match(name)
    return m.group(1) if m else None


def _slug_map() -> dict[str, str]:
    """number -> canonical slug folder name, from Aurarena 3DModels."""
    out: dict[str, str] = {}
    for p in AURARENA_3DMODELS.iterdir():
        if not p.is_dir():
            continue
        n = _num(p.name)
        if n:
            out[n] = p.name
    return out


def _target_filename(fname: str, slug: str) -> str | None:
    """Return the slug-prefixed name for a 3dmodel file, or None to leave it."""
    for suf in SUFFIXES:
        if fname.endswith(suf):
            return f"{slug}{suf}"
    # raw mesh: a .glb that is neither textured nor rigged (and not a backup)
    low = fname.lower()
    if low.endswith(".glb") and "_textured" not in low and "_rigged" not in low:
        return f"{slug}.glb"
    return None


def _rename(src: Path, dst: Path, *, write: bool) -> None:
    if src == dst:
        return
    tag = "" if write else "DRY "
    if dst.exists():
        print(f"  {tag}SKIP (target exists): {src.name} -> {dst.name}")
        return
    print(f"  {tag}{src.name} -> {dst.name}")
    if write:
        src.rename(dst)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="Apply (default: dry run).")
    ap.add_argument("--models-dir", type=Path, default=ROOT / "models")
    args = ap.parse_args()

    slugs = _slug_map()
    if not slugs:
        print(f"No Aurarena slugs found at {AURARENA_3DMODELS}")
        return

    renamed_folders = renamed_files = 0
    # Snapshot folders first (we rename folders as we go).
    folders = [p for p in sorted(args.models_dir.iterdir()) if p.is_dir()]
    for folder in folders:
        n = _num(folder.name)
        if not n or n not in slugs:
            continue
        slug = slugs[n]

        # 1) rename 3dmodel/ files to the slug prefix (folder not renamed yet)
        model_dir = folder / "3dmodel"
        if model_dir.is_dir():
            for f in sorted(model_dir.iterdir()):
                if not f.is_file():
                    continue
                tgt = _target_filename(f.name, slug)
                if tgt and tgt != f.name:
                    if renamed_files == 0:
                        print(f"[{folder.name}] -> slug={slug}")
                    _rename(f, f.with_name(tgt), write=args.write)
                    renamed_files += 1

        # 2) rename the folder itself
        if folder.name != slug:
            print(f"[folder] {folder.name} -> {slug}")
            _rename(folder, folder.with_name(slug), write=args.write)
            renamed_folders += 1

    mode = "APPLIED" if args.write else "DRY RUN (no changes)"
    print(f"\n{mode}: {renamed_folders} folders, {renamed_files} files to rename.")


if __name__ == "__main__":
    main()
