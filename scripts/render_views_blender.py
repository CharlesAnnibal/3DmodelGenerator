"""Headless Blender script — render 6 standard views of a creature model.

Produces transparent-background RGBA PNGs at each view position.
Used by the acceptance test suite to visually validate generation quality.

Usage:
    blender --background --python render_views_blender.py -- \\
        <input_glb> <output_dir> [width] [height]

Output files (in output_dir):
    front.png, back.png, left.png, right.png, top.png, three_quarter.png

Camera positions (spec section 6):
    front        azimuth   0°  elevation  0°
    back         azimuth 180°  elevation  0°
    left         azimuth  90°  elevation  0°
    right        azimuth 270°  elevation  0°
    top          azimuth   0°  elevation 90°
    three_quarter azimuth 45° elevation 30°

All cameras are orthographic, sized to fit the mesh bounding box.
Engine: EEVEE (fast, deterministic). Background: transparent.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> tuple[Path, Path, int, int]:
    try:
        idx = sys.argv.index("--")
        argv = sys.argv[idx + 1:]
    except ValueError:
        raise SystemExit(
            "Usage: blender --background --python render_views_blender.py -- "
            "<input_glb> <output_dir> [width] [height]"
        )
    if len(argv) < 2:
        raise SystemExit("Need at least: input_glb output_dir")
    input_glb = Path(argv[0]).resolve()
    output_dir = Path(argv[1]).resolve()
    width = int(argv[2]) if len(argv) > 2 else 256
    height = int(argv[3]) if len(argv) > 3 else 256
    return input_glb, output_dir, width, height


# ---------------------------------------------------------------------------
# Scene setup
# ---------------------------------------------------------------------------

def _clear_scene() -> None:
    import bpy
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)
    for mat in list(bpy.data.materials):
        bpy.data.materials.remove(mat)


def _import_model(path: Path):
    import bpy
    ext = path.suffix.lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path))
    else:
        raise RuntimeError(f"Unsupported format: {ext}")
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError("No mesh objects after import")
    return meshes


def _world_bbox(objects):
    import numpy as np
    all_pts = []
    for obj in objects:
        mat = obj.matrix_world
        for v in obj.data.vertices:
            co = mat @ v.co
            all_pts.append((co.x, co.y, co.z))
    arr = np.array(all_pts, dtype=np.float64)
    return arr.min(axis=0), arr.max(axis=0)


# ---------------------------------------------------------------------------
# Camera positioning
# ---------------------------------------------------------------------------

def _place_camera(az_deg: float, el_deg: float, target, distance: float, ortho_scale: float):
    """Create (or reuse) and place the scene camera."""
    import bpy
    from mathutils import Vector, Matrix
    import math

    az = math.radians(az_deg)
    el = math.radians(el_deg)

    # Spherical → Cartesian (Y-forward convention: az=0 = +Y)
    cx = distance * math.cos(el) * math.sin(az)
    cy = distance * math.cos(el) * math.cos(az)
    cz = distance * math.sin(el)

    cam_loc = Vector((target[0] + cx, target[1] + cy, target[2] + cz))
    target_v = Vector(target)

    # Look-at rotation
    direction = (target_v - cam_loc).normalized()
    up = Vector((0, 0, 1))
    if abs(direction.dot(up)) > 0.999:
        up = Vector((0, 1, 0))

    rot_matrix = direction.to_track_quat("-Z", "Y").to_matrix().to_4x4()
    cam_loc_matrix = Matrix.Translation(cam_loc)
    cam_matrix = cam_loc_matrix @ rot_matrix

    # Get or create camera
    cam_data = bpy.data.cameras.get("AcceptanceCam")
    if cam_data is None:
        cam_data = bpy.data.cameras.new("AcceptanceCam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = ortho_scale

    cam_obj = bpy.data.objects.get("AcceptanceCam")
    if cam_obj is None:
        cam_obj = bpy.data.objects.new("AcceptanceCam", cam_data)
        bpy.context.collection.objects.link(cam_obj)
    cam_obj.matrix_world = cam_matrix
    bpy.context.scene.camera = cam_obj
    return cam_obj


# ---------------------------------------------------------------------------
# Render setup
# ---------------------------------------------------------------------------

def _setup_eevee(width: int, height: int) -> None:
    import bpy
    scene = bpy.context.scene

    # Use EEVEE (fast, deterministic)
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except Exception:
        scene.render.engine = "BLENDER_EEVEE"

    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True  # transparent background
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"

    # EEVEE samples
    try:
        scene.eevee.taa_render_samples = 16
    except Exception:
        pass


def _add_world_lighting() -> None:
    """Add a simple grey world light so textures are visible."""
    import bpy
    world = bpy.data.worlds.get("AcceptanceWorld")
    if world is None:
        world = bpy.data.worlds.new("AcceptanceWorld")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.5, 0.5, 0.5, 1.0)
        bg.inputs["Strength"].default_value = 1.0
    bpy.context.scene.world = world


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    import bpy
    import numpy as np

    input_glb, output_dir, width, height = _parse_args()
    output_dir.mkdir(parents=True, exist_ok=True)

    _clear_scene()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    _clear_scene()

    print(f"[render_views] Importing: {input_glb}")
    meshes = _import_model(input_glb)

    bbox_min, bbox_max = _world_bbox(meshes)
    center = (bbox_min + bbox_max) * 0.5
    bbox_size = bbox_max - bbox_min
    max_dim = float(bbox_size.max())
    diagonal = float(np.linalg.norm(bbox_size))

    distance = diagonal * 1.8
    ortho_scale = max_dim * 1.2

    _setup_eevee(width, height)
    _add_world_lighting()

    views = [
        ("front",         0,    0),
        ("back",        180,    0),
        ("left",         90,    0),
        ("right",       270,    0),
        ("top",           0,   90),
        ("three_quarter", 45,  30),
    ]

    for view_name, az, el in views:
        dist = diagonal * (2.0 if view_name == "three_quarter" else 1.8)
        _place_camera(az, el, center.tolist(), dist, ortho_scale)

        out_path = str(output_dir / f"{view_name}.png")
        bpy.context.scene.render.filepath = out_path
        bpy.ops.render.render(write_still=True)
        print(f"[render_views] Saved: {out_path}")

    print("[render_views] Done.")


if __name__ == "__main__":
    main()
