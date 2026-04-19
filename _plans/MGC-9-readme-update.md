---
status: done
---

# MGC-9 — README Update + Per-Creature Height Config

## What was done

### Phase 1 — README rewrite
- Rewrote `README.md` to match `_specs/general.md` as the authoritative reference
- Added all missing flags (`--height`, `--small/--medium/--big/--huge`, `--no-fbx`, `--no-acceptance`, `--strict`, `--steps`, `--octree-resolution`, `--seed`)
- Added usage examples for size presets, quality presets, rig profiles, texture size
- Fixed output structure (GLB files, renders/, acceptance.json, correct FBX names)
- Added full flag reference table

### Phase 2 — Image input guidance
- Added **Image input guidance** section to `README.md` and `_specs/MGC-9-flexible-input-views.md`
- Single-image mode: ranked view choices (3/4 best → front → side)
- Three orthographic views: requirements, what works, what doesn't
- Decision table: when to use each mode

### Phase 3 — Per-creature height via config.yaml
- Split `_resolve_target_height(args)` to return `None` when no CLI flag is set
- Added `_read_creature_config(folder)` — reads `config.yaml` with PyYAML; exits with install hint if missing
- Added `_resolve_height_for_creature(args, config)` — applies priority chain: CLI > config.yaml > default
- Updated main loop to read config per creature and pass resolved height to `process_creature()`
- Updated `README.md` input structure section with `config.yaml` example

## Priority chain

```
CLI flag (--height / --small / --big / --huge)
  → config.yaml height key
    → default 1.0 m
```

## Files changed

| File | Change |
|---|---|
| `src/model_generator_cli/__main__.py` | Split height resolver, added config reader, updated main loop |
| `README.md` | Full rewrite + image guidance + config.yaml docs |
| `_specs/MGC-9-flexible-input-views.md` | Image guidance + config.yaml spec + acceptance criteria |
| `_specs/index.md` | Linked plan |

## Key functions added

| Function | File | Purpose |
|---|---|---|
| `_resolve_target_height(args)` | `__main__.py` | Returns `float \| None` — None when no CLI flag set |
| `_read_creature_config(folder)` | `__main__.py` | Reads `config.yaml`, returns dict |
| `_resolve_height_for_creature(args, config)` | `__main__.py` | Applies priority chain, returns final float |

## Dependency added

- `pyyaml` — required only when a `config.yaml` is present. Missing package produces a clear error with install instructions.

## Commit

`9eecc71` — Remove input/output from versioning; add MGC-9 README update  
*(config.yaml feature added after — commit pending)*
