"""Smoke-test the post-processing pipeline without running Hunyuan3D.

Generates a synthetic mesh (no AI inference needed) and runs it through:
  4b  Scale normalization
  4c  Mesh decimation
  5   Fix merged legs  (--no-fix-legs to skip)
  6   Auto-rig         (--no-rig to skip)
  10  Acceptance checks (--no-acceptance to skip)

Texture bake is skipped — it needs real reference images and adds minutes.
The goal is a < 60-second loop to verify pipeline changes before a full run.

Usage
-----
  py -3 test_pipeline.py
  py -3 test_pipeline.py --faces 300000 --name my-test
  py -3 test_pipeline.py --input output/my-creature/3dmodel/my-creature.glb
  py -3 test_pipeline.py --no-fix-legs --no-acceptance
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap sys.path (same as __main__.py)
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent
_CLI_SRC = _ROOT / "src"
_MG_SRC = _ROOT.parent / "modelGenerator" / "src"
_HUNYUAN_SRC = _ROOT.parent / "modelGenerator" / "third_party" / "Hunyuan3D-2"
for _p in (_CLI_SRC, _MG_SRC, _HUNYUAN_SRC):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

_SCRIPTS = _ROOT.parent / "modelGenerator" / "scripts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(n: int) -> str:
    return f"{n:,}"


def _mesh_stats(path: str) -> tuple[int, int]:
    """Return (vertex_count, face_count) for a GLB file."""
    import trimesh
    m = trimesh.load(path, force="mesh", process=False)
    return len(m.vertices), len(m.faces)


def _print_stats(label: str, verts: int, faces: int) -> None:
    v_ok = 5_000 <= verts <= 500_000
    f_ok = 3_000 <= faces <= 1_000_000
    v_mark = "OK" if v_ok else "!!"
    f_mark = "OK" if f_ok else "!!"
    print(f"  {label:<30}  verts={_fmt(verts)} [{v_mark}]  faces={_fmt(faces)} [{f_mark}]")


def _step(label: str) -> float:
    print(f"\n[step] {label}")
    return time.time()


def _done(t0: float) -> None:
    print(f"       done in {time.time() - t0:.1f}s")


# ---------------------------------------------------------------------------
# Synthetic mesh
# ---------------------------------------------------------------------------

def _make_synthetic_mesh(n_faces: int) -> "trimesh.Trimesh":
    """Return a capsule-shaped trimesh with approximately *n_faces* faces.

    A capsule (taller than wide) is close enough to a character silhouette
    for the autorig limb-detection heuristics to run without crashing.
    Subdivision level 7 icosphere gives ~327K faces — enough to stress the
    decimation path.
    """
    import trimesh

    # Icosphere face counts by subdivision level:
    #   5 → 20 480  |  6 → 81 920  |  7 → 327 680
    if n_faces <= 20_480:
        sub = 5
    elif n_faces <= 81_920:
        sub = 6
    else:
        sub = 7

    sphere = trimesh.creation.icosphere(subdivisions=sub)

    # Scale into a tall-ish capsule shape (height > width) so the autorig
    # detects it as "humanoid" rather than "serpentine".
    sphere.apply_scale([0.5, 0.5, 1.0])
    return sphere


# ---------------------------------------------------------------------------
# Pipeline steps (mirrors pipeline.py steps 4b – 10, no Hunyuan)
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    import trimesh

    name: str = args.name
    out_dir = Path(args.output_dir) / name
    model_dir = out_dir / "3dmodel"
    model_dir.mkdir(parents=True, exist_ok=True)

    temp_files: list[Path] = []
    t_total = time.time()

    try:
        # -- Mesh source ---------------------------------------------------
        if args.input:
            src = Path(args.input)
            if not src.is_file():
                sys.exit(f"Input file not found: {src}")
            t0 = _step(f"Loading mesh from {src.name}")
            fd, raw_glb = tempfile.mkstemp(suffix=".glb", prefix=f"{name}_raw_")
            os.close(fd)
            shutil.copy2(src, raw_glb)
            temp_files.append(Path(raw_glb))
            current_glb = raw_glb
            v, f = _mesh_stats(current_glb)
            _print_stats("loaded", v, f)
            _done(t0)
        else:
            t0 = _step(f"Generating synthetic mesh (~{_fmt(args.faces)} faces)")
            mesh = _make_synthetic_mesh(args.faces)
            fd, raw_glb = tempfile.mkstemp(suffix=".glb", prefix=f"{name}_raw_")
            os.close(fd)
            mesh.export(raw_glb)
            temp_files.append(Path(raw_glb))
            current_glb = raw_glb
            v, f = _mesh_stats(current_glb)
            _print_stats("synthetic", v, f)
            _done(t0)

        # -- 4b. Scale normalization ---------------------------------------
        t0 = _step("4b  Scale normalization")
        try:
            import numpy as np
            raw = trimesh.load(current_glb, force="mesh", process=False)
            verts = np.asarray(raw.vertices)
            bbox_z = float(verts[:, 2].max() - verts[:, 2].min())
            if bbox_z > 1e-6:
                scale = args.target_height / bbox_z
                raw.apply_scale(scale)
                fd2, scaled_glb = tempfile.mkstemp(suffix=".glb", prefix=f"{name}_scaled_")
                os.close(fd2)
                raw.export(scaled_glb)
                temp_files.append(Path(scaled_glb))
                current_glb = scaled_glb
                print(f"  scaled by {scale:.3f}x (height -> {args.target_height} m)")
        except Exception as exc:
            print(f"  WARNING: scale normalization failed: {exc}")
        _done(t0)

        # -- 4c. Mesh decimation -------------------------------------------
        _TARGET_FACES = 100_000
        t0 = _step(f"4c  Mesh decimation (target {_fmt(_TARGET_FACES)} faces)")
        decimated_ok = False
        try:
            dec_mesh = trimesh.load(current_glb, force="mesh", process=False)
            n_before = len(dec_mesh.faces)
            if n_before > _TARGET_FACES:
                dec_mesh = dec_mesh.simplify_quadric_decimation(_TARGET_FACES)
                n_after = len(dec_mesh.faces)
                if n_after < n_before:
                    print(f"  trimesh decimated {_fmt(n_before)} -> {_fmt(n_after)} faces")
                    fd3, dec_glb = tempfile.mkstemp(suffix=".glb", prefix=f"{name}_dec_")
                    os.close(fd3)
                    dec_mesh.export(dec_glb)
                    temp_files.append(Path(dec_glb))
                    current_glb = dec_glb
                    decimated_ok = True
                else:
                    print("  trimesh had no effect (fast_simplification missing)")
            else:
                print(f"  already under target ({_fmt(n_before)} faces) -- skipped")
                decimated_ok = True
        except Exception as exc:
            print(f"  trimesh failed: {exc}")

        if not decimated_ok:
            print("  falling back to Blender decimation")
            from model_generator.blender_tools import decimate_via_blender
            bd_glb, bd_msg = decimate_via_blender(
                current_glb, _TARGET_FACES, scripts_dir=_SCRIPTS,
            )
            if bd_glb is not None:
                temp_files.append(Path(bd_glb))
                current_glb = bd_glb
                v, f = _mesh_stats(current_glb)
                _print_stats("after blender decimate", v, f)
            else:
                print(f"  WARNING: blender decimation failed: {bd_msg}")
        _done(t0)

        # -- 5. Fix merged legs --------------------------------------------
        if args.fix_legs:
            t0 = _step("5   Fix merged legs")
            from model_generator.blender_tools import fix_legs_via_blender
            fixed, msg = fix_legs_via_blender(current_glb, args.rig_profile, scripts_dir=_SCRIPTS)
            if fixed is not None:
                temp_files.append(Path(fixed))
                current_glb = fixed
                v, f = _mesh_stats(current_glb)
                _print_stats("after fix-legs", v, f)
            else:
                print(f"  WARNING: {msg}")
            _done(t0)

        # -- 6. Auto-rig ---------------------------------------------------
        if args.auto_rig:
            t0 = _step("6   Auto-rig")
            from model_generator.blender_tools import autorig_via_blender
            rigged, rigged_fbx, rig_manifest, msg = autorig_via_blender(
                current_glb, args.rig_profile, scripts_dir=_SCRIPTS
            )
            if rigged is not None:
                dest = model_dir / f"{name}.glb"
                shutil.copy2(rigged, dest)
                temp_files.append(Path(rigged))
                v, f = _mesh_stats(str(dest))
                _print_stats("after autorig (exported GLB)", v, f)
                print(f"  saved -> {dest}")
                if rigged_fbx:
                    fbx_dest = model_dir / f"{name}_rigged.fbx"
                    shutil.copy2(rigged_fbx, fbx_dest)
                    temp_files.append(Path(rigged_fbx))
                    print(f"  saved -> {fbx_dest}")
                if rig_manifest:
                    man_dest = model_dir / f"{name}_rig_manifest.json"
                    shutil.copy2(rig_manifest, man_dest)
                    temp_files.append(Path(rig_manifest))
                    print(f"  saved -> {man_dest}")
            else:
                print(f"  WARNING: {msg}")
            _done(t0)

        # -- 10. Acceptance ------------------------------------------------
        if args.run_acceptance:
            t0 = _step("10  Acceptance checks")
            try:
                from model_generator_cli.acceptance import run_acceptance
                result = run_acceptance(
                    name,
                    Path(args.output_dir),
                    reference_images={},
                    render=False,
                    target_height=args.target_height,
                )
                status = "PASS" if result.passed else "FAIL"
                print(f"  {status}  score={result.score:.3f}")
                print("  (F-*/T-* failures are expected — texture bake was skipped)")
                for c in result.checks:
                    mark = "OK" if c.passed else "!!"
                    # Encode to ASCII, replacing any non-ASCII chars, so the
                    # Windows cp1252 console doesn't throw UnicodeEncodeError.
                    line = (
                        f"  [{mark}] {c.id} ({c.severity:<8}) {c.name}: {c.value}"
                        f"  (threshold: {c.threshold})"
                    ).encode("ascii", errors="replace").decode("ascii")
                    print(line)
            except Exception as exc:
                print(f"  WARNING: acceptance check error: {exc}")
            _done(t0)

    finally:
        for p in temp_files:
            p.unlink(missing_ok=True)

    print(f"\nTotal: {time.time() - t_total:.1f}s")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="test_pipeline",
        description="Smoke-test post-processing pipeline without Hunyuan3D inference.",
    )
    p.add_argument("--name", default="test-creature",
                   help="Output subfolder name (default: test-creature).")
    p.add_argument("--input", default=None,
                   help="Use an existing GLB instead of generating a synthetic mesh.")
    p.add_argument("--faces", type=int, default=327_680,
                   help="Approximate face count for the synthetic mesh (default: 327680, ~ico7).")
    p.add_argument("--output-dir", default="./output",
                   help="Output root directory (default: ./output).")
    p.add_argument("--target-height", type=float, default=1.0)
    p.add_argument("--rig-profile", default="auto",
                   choices=["auto", "humanoid", "quadruped", "serpentine"])
    p.add_argument("--no-fix-legs", dest="fix_legs", action="store_false")
    p.add_argument("--no-rig", dest="auto_rig", action="store_false")
    p.add_argument("--no-acceptance", dest="run_acceptance", action="store_false")
    p.set_defaults(fix_legs=True, auto_rig=True, run_acceptance=True)
    return p.parse_args(argv)


if __name__ == "__main__":
    run(_parse())
