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

def _parse_args() -> tuple[Path, Path, int, int, bool]:
    try:
        idx = sys.argv.index("--")
        argv = sys.argv[idx + 1:]
    except ValueError:
        raise SystemExit(
            "Usage: blender --background --python render_views_blender.py -- "
            "<input_glb> <output_dir> [width] [height] [--unlit]"
        )
    flags = [a for a in argv if a.startswith("--")]
    positional = [a for a in argv if not a.startswith("--")]
    if len(positional) < 2:
        raise SystemExit("Need at least: input_glb output_dir")
    input_glb = Path(positional[0]).resolve()
    output_dir = Path(positional[1]).resolve()
    width = int(positional[2]) if len(positional) > 2 else 256
    height = int(positional[3]) if len(positional) > 3 else 256
    unlit = "--unlit" in flags
    return input_glb, output_dir, width, height, unlit


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


def _import_model(path: Path, *, unlit: bool = False):
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
    if unlit:
        _convert_to_unlit(meshes)
    else:
        _force_basecolor_srgb(meshes)
    return meshes


def _convert_to_unlit(meshes) -> None:
    """Replace every Principled BSDF with an Emission shader fed by the base-color
    image. Use Non-Color colorspace so PNG bytes pass through without gamma
    correction; combined with view_transform='Raw' this gives pixel-faithful
    rendering — required for UV-position lookup textures."""
    import bpy
    seen: set[str] = set()
    for obj in meshes:
        for slot in getattr(obj, "material_slots", []):
            mat = slot.material
            if mat is None or not mat.use_nodes:
                continue
            tree = mat.node_tree
            principled = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            output = next((n for n in tree.nodes if n.type == "OUTPUT_MATERIAL"), None)
            if principled is None or output is None:
                continue
            base_input = principled.inputs.get("Base Color")
            tex_node = None
            if base_input is not None and base_input.is_linked:
                src = base_input.links[0].from_node
                if src.type == "TEX_IMAGE" and src.image is not None:
                    tex_node = src
            emission = tree.nodes.new("ShaderNodeEmission")
            emission.inputs["Strength"].default_value = 1.0
            if tex_node is not None:
                if tex_node.image.name not in seen:
                    seen.add(tex_node.image.name)
                    try:
                        tex_node.image.colorspace_settings.name = "Non-Color"
                    except Exception:
                        pass
                tree.links.new(tex_node.outputs["Color"], emission.inputs["Color"])
            else:
                color = base_input.default_value if base_input else (1, 1, 1, 1)
                emission.inputs["Color"].default_value = color
            for link in list(output.inputs["Surface"].links):
                tree.links.remove(link)
            tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])


def _force_basecolor_srgb(meshes) -> None:
    """Ensure base-color texture nodes are interpreted as sRGB (not Non-Color).

    glTF importers can leave the base-color image in Linear/Non-Color mode if
    the source PNG lacked an explicit color profile, which renders the albedo
    desaturated. Walk every material and force its Principled BSDF base-color
    image input to sRGB.
    """
    seen: set[str] = set()
    for obj in meshes:
        for slot in getattr(obj, "material_slots", []):
            mat = slot.material
            if mat is None or not mat.use_nodes:
                continue
            tree = mat.node_tree
            principled = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if principled is None:
                continue
            base_input = principled.inputs.get("Base Color")
            if base_input is None or not base_input.is_linked:
                continue
            src = base_input.links[0].from_node
            if src.type != "TEX_IMAGE" or src.image is None:
                continue
            if src.image.name in seen:
                continue
            seen.add(src.image.name)
            try:
                src.image.colorspace_settings.name = "sRGB"
            except Exception:
                pass


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
    """Bright world ambient + 3-point key/fill/rim lights for clear PBR rendering."""
    import bpy
    from mathutils import Vector

    world = bpy.data.worlds.get("AcceptanceWorld")
    if world is None:
        world = bpy.data.worlds.new("AcceptanceWorld")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
        bg.inputs["Strength"].default_value = 1.0
    bpy.context.scene.world = world

    def _add_sun(name: str, location, energy: float, color=(1.0, 1.0, 1.0)):
        if name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)
        light_data = bpy.data.lights.new(name=name, type="SUN")
        light_data.energy = energy
        light_data.color = color
        light_obj = bpy.data.objects.new(name=name, object_data=light_data)
        bpy.context.collection.objects.link(light_obj)
        loc = Vector(location)
        light_obj.location = loc
        direction = (-loc).normalized()
        light_obj.rotation_mode = "QUATERNION"
        light_obj.rotation_quaternion = direction.to_track_quat("-Z", "Y")

    _add_sun("KeyLight",  ( 4.0, -4.0,  6.0), energy=1.0)
    _add_sun("FillLight", (-5.0, -2.0,  3.0), energy=0.5)
    _add_sun("RimLight",  ( 0.0,  5.0,  4.0), energy=0.5)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    import bpy
    import numpy as np

    input_glb, output_dir, width, height, unlit = _parse_args()
    output_dir.mkdir(parents=True, exist_ok=True)

    _clear_scene()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    _clear_scene()

    print(f"[render_views] Importing: {input_glb}{' (unlit)' if unlit else ''}")
    meshes = _import_model(input_glb, unlit=unlit)

    bbox_min, bbox_max = _world_bbox(meshes)
    center = (bbox_min + bbox_max) * 0.5
    bbox_size = bbox_max - bbox_min
    max_dim = float(bbox_size.max())
    diagonal = float(np.linalg.norm(bbox_size))

    distance = diagonal * 1.8
    ortho_scale = max_dim * 1.2

    _setup_eevee(width, height)
    if unlit:
        # Pixel-faithful output: skip lights, set Raw view transform.
        try:
            bpy.context.scene.view_settings.view_transform = "Raw"
        except Exception:
            pass
        # Black world so unmapped pixels are clearly distinguishable from UV (0,0).
        world = bpy.data.worlds.get("AcceptanceWorld") or bpy.data.worlds.new("AcceptanceWorld")
        world.use_nodes = True
        bg = world.node_tree.nodes.get("Background")
        if bg:
            bg.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
            bg.inputs["Strength"].default_value = 0.0
        bpy.context.scene.world = world
    else:
        _add_world_lighting()

    # GLB convention here: front = looking at -Y (azimuth 180°)
    views = [
        ("front",       180,    0),
        ("back",          0,    0),
        ("left",        270,    0),
        ("right",        90,    0),
        ("top",           0,   90),
        ("three_quarter", 225, 30),
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
