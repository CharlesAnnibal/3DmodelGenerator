"""Minimal diagnostic bake: trivial base-color emission, no multi-view graph.
Run via: blender --background --python diag_bake.py -- <input.glb> <out.png>
"""
import sys, bpy

argv = sys.argv[sys.argv.index("--") + 1:]
in_glb, out_png = argv[0], argv[1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=in_glb)
obj = next(o for o in bpy.context.scene.objects if o.type == "MESH")
bpy.ops.object.select_all(action="DESELECT")
bpy.context.view_layer.objects.active = obj
obj.select_set(True)

mesh = obj.data
uv = mesh.uv_layers.new(name="BakeUV")
mesh.uv_layers.active = uv
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.smart_project(angle_limit=1.15)
bpy.ops.object.mode_set(mode="OBJECT")
for name in ("proj_front", "proj_back", "proj_side_pos", "proj_side_neg"):
    extra = mesh.uv_layers.new(name=name)
    for li in range(len(mesh.loops)):
        extra.data[li].uv = (0.5, 0.5)

for u in mesh.uv_layers:
    u.active = (u.name == "BakeUV")
    u.active_render = (u.name == "BakeUV")
print("[diag] uv layers:", [u.name for u in mesh.uv_layers], "active:", mesh.uv_layers.active.name)

mat = bpy.data.materials.new("Diag")
mat.use_nodes = True
nt = mat.node_tree
nt.nodes.clear()
out = nt.nodes.new("ShaderNodeOutputMaterial")
emit = nt.nodes.new("ShaderNodeEmission")
emit.inputs["Color"].default_value = (1.0, 0.3, 0.7, 1.0)  # bright magenta
nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])

img = bpy.data.images.new("diag_bake", 512, 512, alpha=False)
tex = nt.nodes.new("ShaderNodeTexImage")
tex.image = img
nt.nodes.active = tex

obj.data.materials.clear()
obj.data.materials.append(mat)

scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 1
scene.render.bake.margin = 4

bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
print("[diag] baking...")
bpy.ops.object.bake(type="EMIT")
print("[diag] saving...")
img.filepath_raw = out_png
img.file_format = "PNG"
img.save()
print(f"[diag] wrote {out_png}")
