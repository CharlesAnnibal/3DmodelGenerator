# Reference mesh (optional, not uploaded in the UI)

Put a **single** 3D file here to drive the **shape** of exports:

- Preferred name: **`reference.glb`**
- Or any **`.glb`**, **`.gltf`**, or **`.obj`** in this folder (first match wins; sorted order — avoid extra `.glb` test files here)

### FBX → GLB (Python/trimesh cannot read FBX)

Use **Blender** headless with [`scripts/fbx_to_glb_blender.py`](../scripts/fbx_to_glb_blender.py). Example (adjust Blender path if needed):

```powershell
& "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" `
  --background `
  --python "..\scripts\fbx_to_glb_blender.py" `
  -- ".\Burrow.FBX" ".\Burrow.glb"
```

Run the command from this `reference` folder, or use full paths to the FBX and output GLB.

The Gradio app still only asks for an **image**. That image is used as **optional displacement** along surface normals on top of this mesh (slider **Height / displacement**). Set displacement to **0** to export the reference shape unchanged (after **Scale**).

Override path:

```text
set MODEL_GENERATOR_REFERENCE=C:\path\to\model.glb
```

(PowerShell: `$env:MODEL_GENERATOR_REFERENCE = "C:\path\to\model.glb"`)
