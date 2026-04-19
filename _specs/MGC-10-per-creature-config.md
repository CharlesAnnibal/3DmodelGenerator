---
status: draft
---

# MGC-10 — Per-Creature Config File

## Problem

All pipeline flags are global — every creature in a batch run gets the same height, rig profile, texture size, and seed. Processing creatures with different sizes or body types requires separate runs with `--creature`, which defeats the purpose of batch processing.

## Goal

Allow a `config.json` file inside each creature folder to override any pipeline flag for that creature only. Global CLI flags remain the default for creatures without a config.

## Deliverables

1. `config.json` spec — supported keys and their defaults
2. `_detect_config(folder)` helper in `__main__.py` that reads and validates the file
3. Per-creature config merged over global args before `process_creature()` is called
4. `README.md` and `_specs/general.md` updated with config file documentation

## Config file format

`input/{name}/config.json`:

```json
{
  "height": "big",
  "rig_profile": "quadruped",
  "texture_size": 1024,
  "seed": 42,
  "preset": "Hunyuan3D-2 Turbo (faster)"
}
```

All keys are optional. Any key absent falls back to the CLI flag (or its default).

### Supported keys

| Key | Type | Values | CLI equivalent |
|---|---|---|---|
| `height` | string or number | `"small"`, `"medium"`, `"big"`, `"huge"`, or metres as float | `--height` |
| `rig_profile` | string | `"auto"`, `"humanoid"`, `"quadruped"`, `"serpentine"` | `--rig-profile` |
| `texture_size` | integer | `512`, `1024`, `2048`, `4096` | `--texture-size` |
| `seed` | integer | any | `--seed` |
| `preset` | string | valid preset name | `--preset` |
| `steps` | integer | any | `--steps` |

## Scope

### In scope
- Reading `config.json` from the creature input folder
- Merging config over global CLI args (config wins)
- Validation with a clear error message on unknown keys or bad values
- Height preset names (`"big"`, `"huge"`, etc.) resolved the same way as `--height`

### Out of scope
- Flags that control the whole batch (`--input-dir`, `--output-dir`, `--creature`)
- Boolean skip flags (`--no-rembg`, `--no-texture`, etc.) — omitted for simplicity; add in a follow-up if needed

## Acceptance criteria

- [ ] `input/1-pupplynx/config.json` with `{"height": "small"}` produces a 0.3 m model when running the full batch
- [ ] Creature without `config.json` uses the global CLI flag value unchanged
- [ ] Unknown key in `config.json` exits with a clear error naming the invalid key
- [ ] Invalid value (e.g. `"height": "enormous"`) exits with a clear error
- [ ] `config.json` keys are documented in README input structure section
