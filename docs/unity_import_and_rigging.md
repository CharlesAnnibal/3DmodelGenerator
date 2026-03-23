# Unity: import GLB, then rig and texture

## Import the generated GLB

1. Copy the downloaded `.glb` into your Unity project, e.g. `Assets/Models/Generated/`.
2. Select the asset in the Project window.
3. In the **Model** import settings, set **Scale Factor** if the mesh is too large or small.
4. **Rig** tab: for meshes from this tool’s baseline (heightfield), choose **Rig Type: None** until you add bones in a DCC tool.

The baseline mesh is **static** (no skeleton). To animate with **rigs**, you add that in the next step.

## Rigging for animation

Typical workflow:

1. **Blender** (recommended): Import GLB → retopo or clean mesh if needed → **Rigify**, **Auto Rig Pro**, or manual armature → weight paint → export **FBX** or **glTF** with skin weights.
2. **Unity**: Import the rigged FBX/glTF → **Animator** + **Avatar** (often **Generic** for creatures).

Mixamo and similar services can auto-rig humanoids; creatures may need Blender or specialized tools.

## Texturing

1. Unwrap UVs in Blender (or Substance) if you need hand-painted or tiled textures.
2. Assign **PBR** materials in Unity (URP/HDRP **Lit**).

When you replace the baseline with a neural image-to-3D pipeline, you may still need UV cleanup and rigging in Blender for production-quality animation.
