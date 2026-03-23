"""Engine identity for UI and logs (avoid confusion after code updates without restart)."""

from __future__ import annotations

import sys
from importlib import metadata


def engine_version() -> str:
    """Package version from installed metadata, or ``__version__`` fallback."""
    try:
        return metadata.version("model-generator")
    except metadata.PackageNotFoundError:
        from model_generator import __version__

        return __version__


def engine_banner_markdown() -> str:
    """Short markdown line for the Gradio header."""
    ver = engine_version()
    py = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return (
        f"**Engine:** `model-generator` **{ver}** · Python {py} · "
        "*Restart this app after `git pull` or `pip install -e .` so the UI loads new code.*"
    )
