---
status: done
---

# MGC-10 — Per-Creature Config File

## What was done

Extended the `config.yaml` support introduced in MGC-9 (height only) to cover all
per-creature pipeline parameters: `preset`, `steps`, `seed`, `texture_size`, `rig_profile`.

Priority chain for all params: **CLI flag > config.yaml > default**

## Changes

### `src/model_generator_cli/__main__.py`

1. Changed `--preset`, `--steps`, `--seed`, `--texture-size`, `--rig-profile` argparse
   defaults to `None` so CLI-not-set can be distinguished from CLI-set.
2. Added `_PARAM_DEFAULTS` dict with original defaults.
3. Added `_VALID_CONFIG_KEYS` and validators for each key type.
4. Extended `_read_creature_config()` to validate unknown keys (exits with error).
5. Added `_resolve_creature_params(args, config)` — replaces the height-only resolver,
   returns a complete dict of all resolved per-creature params.
6. Updated main loop to unpack resolved params into `process_creature()`.

## Files changed

- `src/model_generator_cli/__main__.py`
- `_specs/index.md`

## Config keys supported

| Key | Type | Values |
|---|---|---|
| `height` | string or float | preset name or metres |
| `preset` | string | valid preset name |
| `steps` | integer | any positive int |
| `seed` | integer | any int |
| `texture_size` | integer | 512 / 1024 / 2048 / 4096 |
| `rig_profile` | string | auto / humanoid / quadruped / serpentine |
