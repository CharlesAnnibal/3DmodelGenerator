"""
Convert FBX → GLB using Blender (headless).

Usage (after Blender is installed and on PATH):

  blender --background --python fbx_to_glb_blender.py -- input.fbx output.glb
"""

from __future__ import annotations

import sys


def main() -> None:
    try:
        idx = sys.argv.index("--")
        args = sys.argv[idx + 1 :]
    except ValueError:
        print("Usage: blender --background --python fbx_to_glb_blender.py -- in.fbx out.glb")
        raise SystemExit(2)

    if len(args) < 2:
        print("Need input.fbx and output.glb paths after --")
        raise SystemExit(2)

    fbx_path = args[0]
    glb_path = args[1]

    import bpy  # type: ignore  # noqa: PLC0415

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=fbx_path)
    bpy.ops.export_scene.gltf(
        filepath=glb_path,
        export_format="GLB",
        export_apply=True,
    )
    print(f"Wrote {glb_path}")


if __name__ == "__main__":
    main()
