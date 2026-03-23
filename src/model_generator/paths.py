"""Project paths and optional reference model location (not uploaded via UI)."""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def reference_model_path() -> Path | None:
    """
    Resolve a reference 3D file placed on disk (e.g. from Tripo, Blender, etc.).

    Order:
    1. MODEL_GENERATOR_REFERENCE — absolute or cwd-relative path to a file
    2. reference/reference.glb next to project root
    3. First *.glb, then *.gltf, then *.obj in reference/
    """
    env = os.environ.get("MODEL_GENERATOR_REFERENCE", "").strip()
    if env:
        p = Path(env).expanduser()
        if not p.is_absolute():
            p = (project_root() / p).resolve()
        if p.is_file():
            return p

    ref_dir = project_root() / "reference"
    preferred = ref_dir / "reference.glb"
    if preferred.is_file():
        return preferred

    if ref_dir.is_dir():
        for pattern in ("*.glb", "*.gltf", "*.obj"):
            matches = sorted(ref_dir.glob(pattern))
            if matches:
                return matches[0]
    return None
