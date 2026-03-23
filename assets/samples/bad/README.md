# Bad / in-progress samples

Put assets here that **show problems** you want to fix.

| Subfolder | What to put |
|-----------|-------------|
| `images/` | The **exact** front / side / top / back / bottom images you uploaded to the app. Name them clearly (e.g. `vulpix-front.png`, `burrow-side.png`). |
| `results/` | Screenshots or GLBs of the **generated** mesh showing the issue. **These files are not updated automatically** — after you change code or sliders, **generate again**, then **copy the new GLB/screenshots here** so comparisons stay honest. |

**RGBA without transparency:** If every pixel is opaque (common exports), the engine ignores alpha and uses **edge brightness** to find the silhouette. Use **true cut-out PNGs** when you can.

**Re-run from CLI (same as the app):** from the `modelGenerator` folder, `python scripts/run_pupplynx_bad_sample.py` writes `results/pupplynx_app_defaults.glb` (Gradio defaults) and `pupplynx_hull_only.glb` (no rounding / luminance sculpt) plus `pupplynx_run_manifest.txt`.

This helps diagnose **input framing**, **mask extraction**, **voxel mapping**, and **sculpting**.
