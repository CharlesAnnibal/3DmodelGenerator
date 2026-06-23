"""Verify that every *_textured_rigged.glb has skin data.

Reports per-creature whether the GLB JSON header contains skin definitions
and whether the mesh primitives carry JOINTS_0 / WEIGHTS_0 attributes.

Usage:
    python scripts/verify_glb_skin.py [--models-dir PATH]
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_glb_json(glb: Path) -> dict | None:
    try:
        with glb.open("rb") as f:
            magic = f.read(4)
            if magic != b"glTF":
                return None
            f.read(8)
            jlen = struct.unpack("<I", f.read(4))[0]
            f.read(4)
            return json.loads(f.read(jlen).decode("utf-8"))
    except Exception:
        return None


def check(glb: Path) -> tuple[bool, str]:
    j = read_glb_json(glb)
    if j is None:
        return False, "could not parse GLB"
    skins = j.get("skins") or []
    if not skins:
        return False, "skins=0 (mesh exported without armature link)"
    joints = skins[0].get("joints") or []
    meshes = j.get("meshes") or []
    if not meshes:
        return False, f"skins={len(skins)} but no meshes"
    attrs = meshes[0]["primitives"][0].get("attributes", {}) if meshes[0].get("primitives") else {}
    has_joints = "JOINTS_0" in attrs
    has_weights = "WEIGHTS_0" in attrs
    if not (has_joints and has_weights):
        return False, f"skins={len(skins)} but mesh attrs missing JOINTS_0/WEIGHTS_0 (have {sorted(attrs)})"
    return True, f"OK skins={len(skins)} joints={len(joints)} attrs include JOINTS_0+WEIGHTS_0"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-dir", type=Path, default=ROOT / "models")
    args = parser.parse_args()

    folders = [p for p in sorted(args.models_dir.iterdir()) if p.is_dir()]
    total = 0
    bad = 0
    for folder in folders:
        for glb in (folder / "3dmodel").glob("*_textured_rigged.glb"):
            if glb.name.endswith(".bak"):
                continue
            total += 1
            ok, msg = check(glb)
            tag = "OK  " if ok else "FAIL"
            if not ok:
                bad += 1
            print(f"{tag} {folder.name}/{glb.name}: {msg}")
    print(f"--- {total} GLB(s); {bad} failing")
    sys.exit(0 if bad == 0 else 1)


if __name__ == "__main__":
    main()
