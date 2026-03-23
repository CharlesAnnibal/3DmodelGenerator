"""
Re-export a GLB through Blender’s glTF exporter (same path as FBX→GLB).

Trimesh’s GLB is often minimal; this normalizes layout/materials for Unity.

  blender --background --python reexport_glb_blender.py -- input.glb output.glb
"""

from __future__ import annotations

import sys


def main() -> None:
    try:
        idx = sys.argv.index("--")
        args = sys.argv[idx + 1 :]
    except ValueError:
        print("Usage: blender --background --python reexport_glb_blender.py -- in.glb out.glb")
        raise SystemExit(2)

    if len(args) < 2:
        print("Need input.glb and output.glb paths after --")
        raise SystemExit(2)

    in_path = args[0]
    out_path = args[1]

    import bpy  # type: ignore  # noqa: PLC0415

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=in_path)
    bpy.ops.export_scene.gltf(
        filepath=out_path,
        export_format="GLB",
        export_apply=True,
    )
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
