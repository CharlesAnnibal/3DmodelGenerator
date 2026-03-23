# Good reference samples

Put assets here that you trust as **examples** of correct inputs and outputs.

| Subfolder | Purpose |
|-----------|---------|
| `images/` | Front / side / top / back / bottom pairs that work with the hull pipeline. |
| `models/` | GLB meshes you consider **gold** references. Includes **`Vulpix.glb`** (FBX → GLB via Blender) as an example. |

## Orthographic views (Y-up, Unity-style)

Use **clear silhouettes** on plain backgrounds. **Same vertical extent** (feet to head) on **front**, **side**, and **back**.

**Bipeds or quadrupeds:** the hull uses your **side** image’s **horizontal** axis as **depth (+Z)**. That axis must be the **profile** of the character (nose–tail or chest–back), **not** a diagonal “3/4” render — otherwise depth will look skewed. The pipeline **crops** each view to the tight silhouette so a **wide empty border** on the side shot does not flatten the 3D shape.

| View | Camera | Image layout |
|------|--------|----------------|
| **Front** | Along **−Z** (into screen) | Columns = **+X**, rows = **+Y** (up) |
| **Side** | Along **−X** (profile) | Columns = **+Z** (forward), rows = **+Y** |
| **Top** | Along **−Y** (from above) | Image **rows** = **+Z**, **columns** = **+X** (same footprint as front width × side depth). |
| **Back** | Along **+Z** (from behind) | Same grid idea as **front** (we flip **X** in code). |
| **Bottom** | Along **+Y** (from below) | Same idea as **top** (paws / belly silhouette). |

The app **resizes** top/bottom to the combined **side depth × front width** grid (rows = **Z**, cols = **X**) and scales the final mesh so **width / height / depth** match **wf : hf : ws** from the masks — body **length** comes from the **side** silhouette and is reinforced when **top**/**bottom** agree on the **XZ** footprint. By default it tries **both** image orientations for top/bottom and keeps the one that **tightens** the hull (set ``MODEL_GENERATOR_NO_AUTO_PLAN_SWAP=1`` to disable). You can still transpose in an editor if both choices are poor.

**Face and ears:** A hull from outlines cannot invent **true** eye sockets or nostrils. Use a **front** render with visible **shading** (eyes darker, nose/highlight brighter) and raise **Luminance depth** in the app (**~0.15–0.25**) so the mesh picks up light relief along depth. **Ears** need the **top** silhouette to show them sticking sideways; if the top omits ears or merges them with the head blob, the 3D mesh will too.

**Four-legged animals:** **Top** strongly constrains body width vs length; **back** separates tail vs head along **Z**; **bottom** can clip the underside between legs if the photo shows clear gaps. The hull **fills** any silhouette that is one solid blob — **leg gaps must appear as real holes** (transparent or background) in **top** and **bottom**; otherwise the mesh will still read as fused at the paws. Optional env **`MODEL_GENERATOR_TOP_BOTTOM_ERODE=1`** and **`MODEL_GENERATOR_VOXEL_OPEN=1`** can help separate legs but may **thin** the mesh — use only if needed.

These folders are **not** read automatically by the generator.
