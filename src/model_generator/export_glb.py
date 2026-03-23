"""Write a trimesh mesh to GLB on disk (Unity-friendly)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import trimesh

from model_generator.blender_glb import blender_reexport_enabled, reexport_glb_via_blender
from model_generator.mesh_post import apply_export_orientation, apply_export_smoothing


def export_glb(mesh: trimesh.Trimesh, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    out_mesh = mesh.copy()
    apply_export_orientation(out_mesh)
    apply_export_smoothing(out_mesh)
    out_mesh.fix_normals()

    if blender_reexport_enabled():
        fd, tmp_name = tempfile.mkstemp(suffix=".glb")
        try:
            os.close(fd)
            tmp_path = Path(tmp_name)
            out_mesh.export(tmp_path, file_type="glb")
            if reexport_glb_via_blender(tmp_path, path):
                return path
        finally:
            Path(tmp_name).unlink(missing_ok=True)

    out_mesh.export(path, file_type="glb")
    return path
