---
status: planned
---

# MGC-12 — Folder Reorganization & Artifact Cleanup

## Problem

The pipeline currently splits each creature across two separate top-level directories (`input/` and `output/`), making it awkward to manage a creature as a unit — moving, archiving, or deleting one requires touching two folders. The `output/{creature}/3dmodel/` directories are also littered with intermediate and debug artifacts (`debug_faceassign.*`, `gltf_buffer_*.bin`, `*_data.bin`, inline `*.gltf` sidecar files, `*_textured_rigged_img*.png`) that are never needed after the pipeline completes, wasting disk space and obscuring the final deliverables.

Root-level diagnostic scripts (`diag_bake.py`, `diagnose2.py`, `diagnose_orientation.py`, `retexture_*.py`, `remove_floor*.py`, `split_image.py`, `test_pipeline.py`, `test_texture_bake.py`) have accumulated and are not part of the pipeline.

## Goal

Each creature lives in a single subfolder under a new top-level `models/` directory. Reference images go in `models/{creature}/images/`; generated outputs write to `models/{creature}/` (same layout as the current `output/` subdirectory). A one-time migration script moves existing `input/` and `output/` data into the new structure, and a `--clean` flag (or standalone command) removes intermediate and debug artifacts from any creature folder.

## Deliverables

1. **Updated pipeline source** — `--input-dir` and `--output-dir` defaults replaced by a single `--models-dir` defaulting to `./models`; creature images read from `{models-dir}/{creature}/images/`; outputs written to `{models-dir}/{creature}/`.
2. **Migration script** (`scripts/migrate_to_models_dir.py`) — moves existing `input/{creature}/*` → `models/{creature}/images/` and `output/{creature}/*` → `models/{creature}/` for all creatures, then removes the now-empty `input/` and `output/` roots.
3. **Cleanup command** — `.\generator clean [--creature NAME]` deletes intermediate and debug artifacts from one or all creature folders (see scope below).

## Scope

### In scope
- New `models/` top-level directory as the single home for all creature data
- Pipeline reads images from `models/{creature}/images/` (replaces `input/{creature}/`)
- Pipeline writes outputs to `models/{creature}/` (replaces `output/{creature}/`)
- `config.yaml` per creature moves from `input/{creature}/config.yaml` → `models/{creature}/images/config.yaml`
- `_processed`-suffix images remain in `images/` alongside originals (no behavior change)
- Migration script for existing `input/` + `output/` data
- Cleanup removes: `debug_faceassign.*`, `gltf_buffer_*.bin`, `*_data.bin`, `*_textured_rigged_img*.png`, `*_textured.gltf`, `*_textured_rigged.gltf`, `*_textured.png` (intermediate embedded texture), `*.gltf` sidecars that duplicate a `.glb` of the same base name
- `general.md` updated to reflect new directory structure and CLI commands

### Out of scope
- Moving root-level diagnostic scripts to `scripts/` (separate cleanup ticket)
- Changing the output subdirectory layout (`3dmodel/`, `textures/`, `renders/`) inside each creature folder
- Changing the final file formats or names

## Acceptance criteria

- [ ] Running `.\generator run --creature 1-pupplynx` with the new code reads images from `models/1-pupplynx/images/` and writes outputs to `models/1-pupplynx/`
- [ ] `config.yaml` is found at `models/{creature}/images/config.yaml` and applied correctly
- [ ] Migration script moves all four existing creatures without data loss; `input/` and `output/` directories are removed afterward
- [ ] `.\generator clean --creature 1-pupplynx` removes all intermediate/debug artifacts listed in scope and leaves only the final deliverables (`*_textured_rigged.fbx`, `*_textured_rigged.glb`, `{name}.png` texture, renders, `acceptance.json`, rig manifest)
- [ ] `.\generator clean` (no `--creature`) cleans all creature folders
- [ ] `general.md` input/output structure section reflects the new layout

## Constraints

- Migration must be non-destructive: dry-run mode (`--dry-run`) prints what would move without touching the filesystem
- The old `--input-dir` / `--output-dir` flags should remain as deprecated aliases pointing into the new structure, so any existing scripts don't break immediately
