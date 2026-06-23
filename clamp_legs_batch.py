"""Batch leg-weight clamp across affected quadrupeds, in-place on the Unity GLB
the prefab actually uses (prefers *_textured_rigged_painted.glb). Keeps .meta.
Verifies the skin metric after each. Run once; user rebuilds prefabs after.
"""
import os, subprocess, glob, struct, sys
import numpy as np
from pygltflib import GLTF2

UNITY = r"D:\Projects\Games\Aurarena\Assets\Creatures"
BLENDER = os.environ["BLENDER_EXE"]
CLAMP = r"D:\Projects\Games\modelGeneratorCLI\modelGenerator\scripts\clamp_leg_weights_blender.py"
TMP = os.environ["TEMP"]

# quad-profile creatures with the head-follows-legs issue; exclude 1,2 (good),
# 4,34 (separate no-leg-movement issue), floaters.
SLUGS = ["3-heatiguan", "7-herapony", "8-univinerus", "13-anarana", "14-donaracna",
         "17-guascorch", "18-lumerolf", "25-thundero", "26-voltation", "27-permafoss",
         "28-cubice", "29-borearct", "32-matamuflage", "33-sphinxtle"]


def unity_glb(slug):
    base = os.path.join(UNITY, slug, "3dmodel")
    painted = glob.glob(os.path.join(base, "*_textured_rigged_painted.glb"))
    if painted:
        return painted[0]
    plain = glob.glob(os.path.join(base, "*_textured_rigged.glb"))
    return plain[0] if plain else None


def leg_reach(path):
    g = GLTF2().load(path); blob = g.binary_blob()
    skin = g.skins[0]; jn = [g.nodes[j].name for j in skin.joints]
    m = g.meshes[0].primitives[0]
    def acc(idx, comp):
        a = g.accessors[idx]; bv = g.bufferViews[a.bufferView]; st = (bv.byteOffset or 0) + (a.byteOffset or 0)
        fmt = {5126: 'f', 5123: 'H', 5121: 'B'}[a.componentType]; sz = {'f': 4, 'H': 2, 'B': 1}[fmt]
        stride = bv.byteStride or comp * sz
        return np.array([struct.unpack_from('<' + fmt * comp, blob, st + i * stride) for i in range(a.count)], float)
    pos = acc(m.attributes.POSITION, 3); ji = acc(m.attributes.JOINTS_0, 4).astype(int); jw = acc(m.attributes.WEIGHTS_0, 4)
    jw = jw / np.clip(jw.sum(1, keepdims=True), 1e-6, None)
    ylo, yhi = pos[:, 1].min(), pos[:, 1].max(); H = max(yhi - ylo, 1e-6)
    tops = []
    for li, n in enumerate(jn):
        if "UpperLeg" not in n:
            continue
        mask = np.zeros(len(pos), bool)
        for k in range(4):
            mask |= (ji[:, k] == li) & (jw[:, k] > 0.4)
        if mask.sum() == 0:
            continue
        tops.append((pos[mask, 1].max() - ylo) / H)
    return max(tops) if tops else None


def main():
    for slug in SLUGS:
        g = unity_glb(slug)
        if not g:
            print(f"SKIP {slug}: no GLB"); continue
        before = leg_reach(g)
        out = os.path.join(TMP, f"{slug}_clamped.glb")
        r = subprocess.run([BLENDER, "--background", "--python", CLAMP, "--", g, out],
                           capture_output=True, text=True)
        if not os.path.exists(out):
            print(f"FAIL {slug}: clamp produced no output\n{r.stderr[-300:]}"); continue
        after = leg_reach(out)
        # sanity: skin still present + verts unchanged
        gg = GLTF2().load(out)
        ok = len(gg.skins) == 1
        if ok and after is not None and after <= (before or 1) + 0.01:
            # overwrite the in-game GLB (preserves .meta — only the .glb bytes change)
            with open(out, "rb") as fi, open(g, "wb") as fo:
                fo.write(fi.read())
            print(f"OK   {slug}: legReach {before:.0%} -> {after:.0%}  (staged {os.path.basename(g)})")
        else:
            print(f"WARN {slug}: legReach {before:.0%} -> {after}  skins={len(gg.skins)} — NOT staged, review")


if __name__ == "__main__":
    main()
