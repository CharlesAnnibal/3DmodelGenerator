"""Optional Blender re-export so GLBs match the same glTF pipeline as reference assets."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def _project_scripts_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts"


def find_blender_executable() -> Path | None:
    env = os.environ.get("BLENDER_EXE", "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_file():
            return p

    which = shutil.which("blender")
    if which:
        return Path(which)

    roots = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Blender Foundation",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Blender Foundation",
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for blender_exe in sorted(root.glob("Blender *\\blender.exe")):
            return blender_exe
    return None


def reexport_glb_via_blender(src_glb: Path, dst_glb: Path) -> bool:
    """
    Run Blender headless: import ``src_glb``, export ``dst_glb`` (GLB, export_apply=True).
    Returns True if ``dst_glb`` was written and is non-empty.
    """
    blender = find_blender_executable()
    script = _project_scripts_dir() / "reexport_glb_blender.py"
    if blender is None or not script.is_file():
        return False

    dst_glb.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            [
                str(blender),
                "--background",
                "--python",
                str(script),
                "--",
                str(src_glb.resolve()),
                str(dst_glb.resolve()),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False

    if proc.returncode != 0:
        return False
    return dst_glb.is_file() and dst_glb.stat().st_size > 0


def blender_reexport_enabled() -> bool:
    if os.environ.get("MODEL_GENERATOR_NO_BLENDER_REEXPORT", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return False
    return find_blender_executable() is not None
