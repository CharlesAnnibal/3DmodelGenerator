"""Diagnose which axis a GLB creature faces in mesh coord space."""
import sys
import numpy as np
import trimesh

GLB = r"C:\Users\charl\Projects\Games\modelGeneratorCLI\output\1-pupplynx\3dmodel\1-pupplynx.glb"

mesh = trimesh.load(GLB, force="mesh", process=False)
print(f"Loaded: {len(mesh.vertices)} verts / {len(mesh.faces)} faces")

V = np.asarray(mesh.vertices, dtype=np.float64)
fn = np.asarray(mesh.face_normals, dtype=np.float64)
fc = V[mesh.faces].mean(axis=1)  # face centroids

bbox_min = V.min(axis=0); bbox_max = V.max(axis=0)
extent = bbox_max - bbox_min
print(f"\nBBox min: {bbox_min}")
print(f"BBox max: {bbox_max}")
print(f"Extent:   {extent}")
print(f"Longest axis: {'XYZ'[int(np.argmax(extent))]}  shortest: {'XYZ'[int(np.argmin(extent))]}")

abs_n = np.abs(fn)
dom = np.argmax(abs_n, axis=1)  # 0=X, 1=Y, 2=Z
print(f"\nDominant-normal distribution (all faces):")
for ax in (0, 1, 2):
    cnt = int((dom == ax).sum())
    print(f"  |{'XYZ'[ax]}| dominant: {cnt} ({100.0*cnt/len(fn):.1f}%)")

# Signed distribution along each axis (faces pointing in +axis vs -axis)
for ax in (0, 1, 2):
    pos = int(((dom == ax) & (fn[:, ax] > 0)).sum())
    neg = int(((dom == ax) & (fn[:, ax] < 0)).sum())
    print(f"  +{'XYZ'[ax]}: {pos}   -{'XYZ'[ax]}: {neg}")

# Sample extreme faces on each axis: find faces with centroid at extreme along axis,
# then print their normals.
print("\n--- Most-extreme-centroid faces per axis ---")
for ax, label in ((0, "X"), (1, "Y"), (2, "Z")):
    # +axis extreme (e.g. "the front of the bbox along +Z")
    idx_max = np.argsort(fc[:, ax])[-10:][::-1]
    idx_min = np.argsort(fc[:, ax])[:10]
    print(f"\n10 faces with max {label} (centroid near +{label} bbox face):")
    for i in idx_max:
        print(f"  centroid={fc[i].round(3)}  normal={fn[i].round(3)}")
    print(f"10 faces with min {label} (centroid near -{label} bbox face):")
    for i in idx_min:
        print(f"  centroid={fc[i].round(3)}  normal={fn[i].round(3)}")

# Specifically: for the creature's "face", we expect a cluster of faces pointing along
# whatever is "forward". Let's sum the "outward-ness" of faces per direction.
# For each axis direction, count faces whose centroid is on that side AND whose normal
# points that way (genuine outward faces).
print("\n--- Outward-face counts per signed axis ---")
center = (bbox_min + bbox_max) / 2
for ax, label in ((0, "X"), (1, "Y"), (2, "Z")):
    for sgn, sname in ((+1, "+"), (-1, "-")):
        # faces on the +label side of center, normal pointing that way
        on_side = (fc[:, ax] - center[ax]) * sgn > 0
        pointing = fn[:, ax] * sgn > 0.5
        dominant = dom == ax
        cnt = int((on_side & pointing & dominant).sum())
        print(f"  {sname}{label} outward faces: {cnt}")
