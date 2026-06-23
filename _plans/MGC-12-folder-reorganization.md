---
status: planned
---

# MGC-12 — Folder Reorganization & Artifact Cleanup

## Overview

Three coordinated changes:
1. Collapse `input/{creature}/` and `output/{creature}/` into a single `models/{creature}/` tree, with reference images in an `images/` subfolder.
2. Add a `clean` subcommand that deletes intermediate/debug artifacts from creature folders.
3. Provide a one-time migration script for existing data.

`pipeline.py` needs no changes — it already writes to `output_dir / name / ...`, so passing `models_dir` as `output_dir` produces the correct layout automatically.

---

## Changes

### `src/model_generator_cli/__main__.py`

**1. New `--models-dir` flag (replaces `--input-dir` / `--output-dir`)**

In `_parse_args()`, add before the existing flags:

```python
parser.add_argument(
    "--models-dir", type=Path, default=Path("./models"),
    help="Root directory containing creature subfolders (images in + models out).",
)
```

Keep `--input-dir` and `--output-dir` but mark them deprecated in `help=` text. In `main()`, if either legacy flag is explicitly passed, warn and map them:

```python
if args.input_dir != Path("./input") or args.output_dir != Path("./output"):
    warnings.warn("--input-dir/--output-dir are deprecated; use --models-dir", DeprecationWarning)
    # legacy mode: scan input_dir, write to output_dir as before
```

**2. Update creature scanning**

`_scan_creatures` is unchanged — it still iterates subdirectories of the root dir.
In `main()`, change:

```python
# before
input_dir = args.input_dir.resolve()
output_dir = args.output_dir.resolve()
creatures = _scan_creatures(input_dir, args.creature)

# after
models_dir = args.models_dir.resolve()
models_dir.mkdir(parents=True, exist_ok=True)
creatures = _scan_creatures(models_dir, args.creature)
```

**3. Update `_detect_images` and `_detect_texture_images`**

Both functions currently look in `folder` directly. Add an `images/` subdir fallback:

```python
def _detect_images(folder: Path) -> dict[str, Path]:
    search_dir = folder / "images" if (folder / "images").is_dir() else folder
    # rest of existing logic, using search_dir instead of folder
```

Same pattern for `_detect_texture_images`.

**4. Update `_read_creature_config`**

```python
def _read_creature_config(folder: Path) -> dict:
    for config_path in [folder / "images" / "config.yaml", folder / "config.yaml"]:
        if config_path.is_file():
            ...
```

**5. Pass `models_dir` as output dir to pipeline**

```python
run_creature(..., output_dir=models_dir, ...)
```

This makes `pipeline.py` write to `models/{creature}/3dmodel/`, etc. — correct with zero pipeline changes.

**6. Add `clean` subcommand**

Restructure `_parse_args` to use subparsers:

```python
subparsers = parser.add_subparsers(dest="command", required=True)

run_parser = subparsers.add_parser("run", ...)
# ... move all existing flags to run_parser ...

clean_parser = subparsers.add_parser("clean", help="Remove intermediate/debug artifacts.")
clean_parser.add_argument("--models-dir", type=Path, default=Path("./models"))
clean_parser.add_argument("--creature", default=None)
clean_parser.add_argument("--dry-run", action="store_true")
```

Add `_clean_creature(folder: Path, dry_run: bool)` function:

```python
_GARBAGE_PATTERNS = [
    "debug_faceassign.*",
    "gltf_buffer_*.bin",
    "*_data.bin",
    "*_textured_rigged_img*.png",
    "*_textured.gltf",
    "*_textured_rigged.gltf",
    "*_textured.png",          # intermediate embedded texture (not the baked albedo)
]
```

For each pattern, glob inside `folder/3dmodel/` and delete (or print if `--dry-run`).

**7. Update `generator.bat` and `generator.ps1`**

Add `clean` dispatch alongside `run` in both wrapper scripts.

---

### `scripts/migrate_to_models_dir.py` (new file)

One-time script. Usage: `python scripts/migrate_to_models_dir.py [--dry-run]`

Logic:

```
for each creature in input/:
    mkdir models/{creature}/images/
    move input/{creature}/* → models/{creature}/images/

for each creature in output/:
    move output/{creature}/3dmodel/ → models/{creature}/3dmodel/
    move output/{creature}/textures/ → models/{creature}/textures/
    move output/{creature}/renders/  → models/{creature}/renders/
    move output/{creature}/acceptance.json → models/{creature}/acceptance.json

rmdir input/  (if now empty)
rmdir output/ (if now empty)
```

- `--dry-run` prints moves without touching the filesystem.
- Skips any creature that already exists in `models/` (don't overwrite).
- Prints a summary of what was moved / skipped.

---

### `_specs/general.md`

Update **Input Structure** section:

```
models/
  {name}/
    images/
      front.png          (required — at least one view)
      back.png           (optional)
      side.png           (optional, aliased to left)
      left.png           (optional)
      right.png          (optional)
      config.yaml        (optional per-creature overrides)
    3dmodel/
      {name}_textured_rigged.glb    ← final GLB
      {name}_textured_rigged.fbx    ← final FBX
      {name}_rig_manifest.json
    textures/
      {name}.png
    renders/
      front.png, back.png, left.png, right.png, top.png, three_quarter.png
    acceptance.json
```

Update **CLI Commands** section to use `--models-dir` and add `clean` command.

---

### `_plans/general.md`

Update **Step 1. Load Images** to reflect `{creature}/images/` path.
Update **Output Structure** section to show `models/{name}/` layout.
Update **CLI Flags** table: replace `--input-dir` / `--output-dir` with `--models-dir`.

---

## Files changed

| File | Change |
|---|---|
| `src/model_generator_cli/__main__.py` | `--models-dir` flag; `images/` subdir image detection; `clean` subcommand; legacy flag deprecation |
| `generator.bat` | Add `clean` dispatch |
| `generator.ps1` | Add `clean` dispatch |
| `scripts/migrate_to_models_dir.py` | New migration script |
| `_specs/general.md` | Updated directory structure and CLI docs |
| `_plans/general.md` | Updated pipeline step 1 and output structure |

`pipeline.py` and `acceptance.py` require **no changes**.
