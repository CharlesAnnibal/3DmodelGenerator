"""Second-level diagnostic: where is the 'face' (eyes, snout)?"""
import numpy as np
import trimesh

GLB = r"C:\Users\charl\Projects\Games\modelGeneratorCLI\output\1-pupplynx\3dmodel\1-pupplynx.glb"
mesh = trimesh.load(GLB, force="mesh", process=False)
V = np.asarray(mesh.vertices, dtype=np.float64)
fn = np.asarray(mesh.face_normals, dtype=np.float64)
fc = V[mesh.faces].mean(axis=1)

bbox_min = V.min(axis=0); bbox_max = V.max(axis=0)
print("BBox:", bbox_min.round(3), "->", bbox_max.round(3))
print("Extent:", (bbox_max-bbox_min).round(3))

# The most "pointy" end — i.e., where the mesh narrows to a tip. Look at the
# cross-section (Y,Z) size near each end of the X axis. A snout means at +X
# edge, the mesh is very narrow in Y and Z. A tail might be narrow too.
# Compute for thin X slices at both ends and for Z ends.
def slice_stats(axis, pos, thickness=0.02):
    in_slice = np.abs(V[:, axis] - pos) < thickness
    if not in_slice.any():
        return None
    other_axes = [i for i in range(3) if i != axis]
    vs = V[in_slice]
    return {
        "count": int(in_slice.sum()),
        f"range_{'XYZ'[other_axes[0]]}": (vs[:, other_axes[0]].min(), vs[:, other_axes[0]].max()),
        f"range_{'XYZ'[other_axes[1]]}": (vs[:, other_axes[1]].min(), vs[:, other_axes[1]].max()),
    }

# Sample slices at 10%, 30%, 50%, 70%, 90% along each axis
for ax, label in ((0, "X"), (1, "Y"), (2, "Z")):
    print(f"\n--- Slices along {label} ---")
    lo, hi = bbox_min[ax], bbox_max[ax]
    for frac in (0.05, 0.15, 0.3, 0.5, 0.7, 0.85, 0.95):
        pos = lo + frac * (hi - lo)
        s = slice_stats(ax, pos, thickness=0.015)
        if s:
            keys = [k for k in s if k.startswith("range")]
            sizes = {k: s[k][1] - s[k][0] for k in keys}
            print(f"  {label}={pos:+.3f} ({frac*100:.0f}%)  verts={s['count']:5d}  "
                  + "  ".join(f"{k[-1]}size={sizes[k]:.3f}" for k in keys))

# Now: compare cross-section area narrowing. The creature's SNOUT end will
# have small cross-section. Tail end may also be narrow but often thinner.
# Most importantly, check symmetry: a creature facing +Z has symmetric left-right
# about X=0 at any Z slice.
print("\n--- X-symmetry check (is the mesh mirror-symmetric about X=0?) ---")
# For each vert, find a counterpart with flipped X. Roughly: bin verts and check.
from scipy.spatial import cKDTree
V_mirror = V.copy(); V_mirror[:, 0] *= -1
tree = cKDTree(V)
d, _ = tree.query(V_mirror, k=1)
print(f"X-mirror match: {(d < 0.005).sum()}/{len(V)} verts within 5mm ({100.0*(d<0.005).sum()/len(V):.1f}%)")

print("\n--- Y-symmetry check (is the mesh mirror-symmetric about Y=0?) ---")
V_mirror = V.copy(); V_mirror[:, 1] *= -1
d, _ = tree.query(V_mirror, k=1)
print(f"Y-mirror match: {(d < 0.005).sum()}/{len(V)} verts within 5mm ({100.0*(d<0.005).sum()/len(V):.1f}%)")

print("\n--- Z-symmetry check (is the mesh mirror-symmetric about Z=0?) ---")
V_mirror = V.copy(); V_mirror[:, 2] *= -1
d, _ = tree.query(V_mirror, k=1)
print(f"Z-mirror match: {(d < 0.005).sum()}/{len(V)} verts within 5mm ({100.0*(d<0.005).sum()/len(V):.1f}%)")
