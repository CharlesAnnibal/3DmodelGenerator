"""Terminal progress helpers using tqdm.

Tracks step timings across runs to produce a realistic per-creature progress
bar driven by historical averages.  Timings live in
``<cli root>/.step_times.json`` and each step keeps a rolling window of the
last 20 durations.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from tqdm import tqdm

# ANSI color codes
_RED = "\033[91m"
_YELLOW = "\033[93m"
_GREEN = "\033[92m"
_CYAN = "\033[96m"
_RESET = "\033[0m"
_BOLD = "\033[1m"

# Historical step timings (shared across all creatures / runs).
_HISTORY_FILE = Path(__file__).resolve().parents[2] / ".step_times.json"
_MAX_SAMPLES = 20
# Fallback when no history exists — ~7 min: a rough full-pipeline estimate so
# the bar isn't wildly off on the first run.
_DEFAULT_TOTAL_SECONDS = 7 * 60


# ---------------------------------------------------------------------------
# Step label normalization
# ---------------------------------------------------------------------------

def _canonical(label: str) -> str:
    """Strip dynamic content so variants of the same step share a key.

    E.g. ``"Decimating mesh (327,680 -> 100,000 faces)"`` and
    ``"Decimating mesh (200,000 -> 100,000 faces)"`` collapse to
    ``"Decimating mesh"``.
    """
    label = re.sub(r"\([^)]*\)", "", label)
    label = re.sub(r"\b\d+(\.\d+)?\b", "", label)
    return " ".join(label.split()).strip().lower()


# ---------------------------------------------------------------------------
# StepTracker: per-creature inner progress bar fed by historical averages
# ---------------------------------------------------------------------------

class StepTracker:
    def __init__(self, creature_name: str):
        self.creature_name = creature_name
        self.history: dict[str, dict] = self._load_history()
        self.current_step_key: str | None = None
        self.current_step_label: str | None = None
        self.current_step_started_at: float = 0.0
        self.recorded: dict[str, float] = {}  # this run
        self.creature_started_at = time.time()
        self.expected_total = max(self._estimate_total(), 1.0)

        self.bar = tqdm(
            total=int(self.expected_total),
            desc=f"  [{creature_name}]",
            position=1,
            leave=False,
            bar_format=(
                "  {desc} {percentage:3.0f}%|{bar}| "
                "{elapsed}/~{remaining} {postfix}"
            ),
        )
        self.bar.set_postfix_str("starting")

        # Background ticker so the bar keeps advancing during long steps
        # (e.g. Hunyuan3D diffusion sampling) even without new step_status calls.
        self._stop_evt = threading.Event()
        self._ticker = threading.Thread(target=self._tick_loop, daemon=True)
        self._ticker.start()

    def _tick_loop(self) -> None:
        while not self._stop_evt.wait(1.0):
            try:
                self._refresh()
            except Exception:
                return

    # -- history I/O ---------------------------------------------------------

    def _load_history(self) -> dict[str, dict]:
        if not _HISTORY_FILE.is_file():
            return {}
        try:
            return json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_history(self) -> None:
        try:
            _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            _HISTORY_FILE.write_text(
                json.dumps(self.history, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    def _avg(self, key: str) -> float:
        entry = self.history.get(key) or {}
        samples = entry.get("samples") or []
        return (sum(samples) / len(samples)) if samples else 0.0

    def _estimate_total(self) -> float:
        if not self.history:
            return float(_DEFAULT_TOTAL_SECONDS)
        total = sum(self._avg(k) for k in self.history)
        return total if total > 1.0 else float(_DEFAULT_TOTAL_SECONDS)

    def _record(self, key: str, duration: float) -> None:
        entry = self.history.setdefault(key, {"samples": []})
        samples = entry.setdefault("samples", [])
        samples.append(float(duration))
        if len(samples) > _MAX_SAMPLES:
            del samples[: len(samples) - _MAX_SAMPLES]

    # -- step transitions ----------------------------------------------------

    def begin_step(self, label: str) -> None:
        now = time.time()
        if self.current_step_key is not None:
            dur = now - self.current_step_started_at
            self.recorded[self.current_step_key] = dur
            self._record(self.current_step_key, dur)

        self.current_step_label = label
        self.current_step_key = _canonical(label)
        self.current_step_started_at = now
        self._refresh()

    def finish(self) -> None:
        self._stop_evt.set()
        now = time.time()
        if self.current_step_key is not None:
            dur = now - self.current_step_started_at
            self.recorded[self.current_step_key] = dur
            self._record(self.current_step_key, dur)
            self.current_step_key = None
            self.current_step_label = None

        # Force the bar to full so the completion reads cleanly.
        self.bar.n = self.bar.total
        self.bar.set_postfix_str("done")
        self.bar.refresh()
        self.bar.close()
        self._save_history()

    def _refresh(self) -> None:
        elapsed = time.time() - self.creature_started_at
        # Advance by elapsed time against the historical expected total.
        # This gives a realistic ETA without relying on discrete step weights.
        target_n = min(int(elapsed), self.bar.total)
        delta = target_n - self.bar.n
        if delta > 0:
            self.bar.update(delta)
        self.bar.set_postfix_str(self.current_step_label or "")
        self.bar.refresh()


# ---------------------------------------------------------------------------
# Module-level active tracker (set by __main__ around each creature)
# ---------------------------------------------------------------------------

_active: StepTracker | None = None


def begin_creature(creature_name: str) -> StepTracker:
    """Start tracking a creature and return the tracker (also stored as module-level active)."""
    global _active
    _active = StepTracker(creature_name)
    return _active


def end_creature() -> None:
    global _active
    if _active is not None:
        _active.finish()
        _active = None


# ---------------------------------------------------------------------------
# Public bar/print helpers
# ---------------------------------------------------------------------------

def creature_bar(total: int):
    """Outer progress bar tracking creature count."""
    return tqdm(
        total=total,
        desc="Creatures",
        unit="creature",
        position=0,
        leave=True,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
    )


def step_status(creature_name: str, step: str) -> None:
    """Print a status line and advance the active creature's inner bar."""
    if _active is not None and _active.creature_name == creature_name:
        _active.begin_step(step)
    tqdm.write(f"  {_CYAN}[{creature_name}]{_RESET} {step}")


def warn(creature_name: str, message: str) -> None:
    tqdm.write(f"  {_YELLOW}[{creature_name}] WARNING: {message}{_RESET}")


def error(creature_name: str, message: str) -> None:
    tqdm.write(f"  {_RED}[{creature_name}] ERROR: {message}{_RESET}")


def success(creature_name: str, message: str) -> None:
    tqdm.write(f"  {_GREEN}[{creature_name}] {message}{_RESET}")


def header(text: str) -> None:
    tqdm.write(f"\n{_BOLD}{text}{_RESET}")
