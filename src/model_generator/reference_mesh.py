"""Load an external mesh file and merge to a single Trimesh (offline, no UI upload)."""

from __future__ import annotations

from pathlib import Path

import trimesh


def load_reference_mesh(path: str | Path) -> trimesh.Trimesh:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Reference mesh not found: {path}")

    loaded = trimesh.load(str(path), force=None)
    if isinstance(loaded, trimesh.Scene):
        meshes = [
            g
            for g in loaded.geometry.values()
            if isinstance(g, trimesh.Trimesh) and len(g.faces) > 0
        ]
        if not meshes:
            raise ValueError(f"No triangle meshes in scene: {path}")
        mesh = trimesh.util.concatenate(meshes)
    elif isinstance(loaded, trimesh.Trimesh):
        mesh = loaded
    else:
        raise ValueError(f"Unsupported load result from {path}: {type(loaded)}")

    if len(mesh.faces) == 0:
        raise ValueError(f"Empty mesh: {path}")

    mesh.process()
    mesh.fix_normals()
    return mesh
