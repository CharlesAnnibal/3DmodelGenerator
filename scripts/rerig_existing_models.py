"""Batch re-rig existing generated creature GLBs.

This repairs rig placement without regenerating geometry or textures. For each
creature it reads the existing rig manifest to keep the same profile, uses
`*_textured.glb` as the source, then overwrites:

  *_textured_rigged.glb
  *_textured_rigged.fbx
  *_rig_manifest.json

Optional per-creature anchors can be supplied in config.yaml:

rig_anchors:
  Hips: [0.0, -0.04, 0.02]
  FrontLeftUpperLeg: [-0.06, 0.10, 0.02]
  FrontLeftLowerLeg: [-0.06, 0.10, -0.07]
  FrontLeftFoot: [-0.06, 0.10, -0.16]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modelGenerator" / "src"))

from model_generator.blender_tools import autorig_via_blender  # noqa: E402


def _read_config(folder: Path) -> dict:
    for path in (folder / "images" / "config.yaml", folder / "config.yaml"):
        if not path.is_file():
            continue
        try:
            import yaml
        except ImportError:
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    return {}


def _first(paths):
    found = sorted(paths)
    return found[0] if found else None


def _backup(path: Path) -> None:
    if not path.exists():
        return
    backup = path.with_suffix(path.suffix + ".bak")
    if backup.exists():
        return
    shutil.copy2(path, backup)


def rerig_creature(folder: Path, *, dry_run: bool, backup: bool) -> bool:
    model_dir = folder / "3dmodel"
    # Prefer the un-rigged textured source; fall back to the rigged GLB when the
    # un-rigged copy was purged. The rigged variant still carries the textured
    # mesh, just with stale (or missing) skin data — autorig overwrites the rig.
    source = _first(model_dir.glob("*_textured.glb"))
    if source is None:
        rigged_candidates = [
            p for p in model_dir.glob("*_textured_rigged.glb") if not p.name.endswith(".bak")
        ]
        if rigged_candidates:
            source = sorted(rigged_candidates)[0]
            print(f"NOTE {folder.name}: using rigged GLB as source ({source.name})")
    if source is None:
        print(f"SKIP {folder.name}: missing *_textured*.glb")
        return False

    # Manifest is optional: it's only used to recover the old profile, which a
    # config.yaml rig_profile overrides anyway. Creatures that were never rigged
    # (no manifest) can still be rigged from their textured GLB + config profile;
    # autorig writes a fresh manifest. Falls back to "auto" detection if neither.
    manifest = _first(model_dir.glob("*_rig_manifest.json"))
    manifest_data = json.loads(manifest.read_text(encoding="utf-8")) if manifest else {}
    cfg = _read_config(folder)
    profile = str(cfg.get("rig_profile") or manifest_data.get("profile") or "auto")
    if source.name.endswith("_textured.glb"):
        stem = source.name[: -len("_textured.glb")]
    elif source.name.endswith("_textured_rigged.glb"):
        stem = source.name[: -len("_textured_rigged.glb")]
    else:
        stem = source.stem
    out_glb = model_dir / f"{stem}_textured_rigged.glb"
    out_fbx = model_dir / f"{stem}_textured_rigged.fbx"
    out_manifest = model_dir / f"{stem}_rig_manifest.json"
    anchors = cfg.get("rig_anchors")

    print(f"{'DRY ' if dry_run else ''}RIG {folder.name}: {source.name} profile={profile}")
    if dry_run:
        return True

    rigged, rigged_fbx, new_manifest, msg = autorig_via_blender(
        str(source),
        profile,
        scripts_dir=ROOT / "modelGenerator" / "scripts",
        export_fbx=True,
        rig_anchors=anchors if isinstance(anchors, dict) else None,
    )
    if rigged is None:
        print(f"FAIL {folder.name}: {msg}")
        return False

    if backup:
        for path in (out_glb, out_fbx, out_manifest):
            _backup(path)

    shutil.copy2(rigged, out_glb)
    if rigged_fbx:
        shutil.copy2(rigged_fbx, out_fbx)
    if new_manifest:
        shutil.copy2(new_manifest, out_manifest)

    for temp in (rigged, rigged_fbx, new_manifest):
        if temp:
            Path(temp).unlink(missing_ok=True)

    print(f"OK {folder.name}: wrote {out_glb.name}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-dir", type=Path, default=ROOT / "models")
    parser.add_argument("--creature", action="append", help="Folder name to re-rig; repeatable.")
    parser.add_argument("--write", action="store_true", help="Actually overwrite rigged outputs.")
    parser.add_argument("--no-backup", action="store_true", help="Do not create .bak files before overwrite.")
    args = parser.parse_args()

    folders = [p for p in sorted(args.models_dir.iterdir()) if p.is_dir()]
    if args.creature:
        wanted = set(args.creature)
        folders = [p for p in folders if p.name in wanted]

    ok = 0
    fail = 0
    for folder in folders:
        if rerig_creature(folder, dry_run=not args.write, backup=not args.no_backup):
            ok += 1
        else:
            fail += 1
    print(f"Done: {ok} ok, {fail} failed/skipped")


if __name__ == "__main__":
    main()
