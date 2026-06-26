"""
Model auto-detection for RE4x SD Enhance.

Scans ``script/models/`` for ``.param`` files and returns a deduplicated
list of available models.  Scale variants (e.g. ``realesr-animevideov3-x2``,
``realesr-animevideov3-x3``, ``realesr-animevideov3-x4``) are collapsed into
a single entry with the maximum scale detected.
"""

import os
import re

# ── Known model metadata ──────────────────────────────────────────────────

DISPLAY_NAMES = {
    "realesr-animevideov3": "RealESRGAN AnimeVideo v3",
    "realesrgan-x4plus": "R-ESRGAN 4x+",
    "realesrgan-x4plus-anime": "R-ESRGAN 4x+ Anime",
}

DESCRIPTIONS = {
    "realesr-animevideov3": "Anime video (recommended, 2x/3x/4x)",
    "realesrgan-x4plus": "General image (4x)",
    "realesrgan-x4plus-anime": "Anime image (4x)",
}


# ── Helpers ───────────────────────────────────────────────────────────────

def _infer_display_name(name: str) -> str:
    """Return a human-readable display name, falling back to title-casing."""
    if name in DISPLAY_NAMES:
        return DISPLAY_NAMES[name]
    return name.replace("-", " ").title()


def _infer_description(name: str, max_scale: int) -> str:
    """Return a short description, falling back to a generic one."""
    if name in DESCRIPTIONS:
        return DESCRIPTIONS[name]
    return f"{name} ({max_scale}x)"


# ── Public API ────────────────────────────────────────────────────────────

def get_available_models(models_dir: str) -> list[dict]:
    """Scan *models_dir* for ``.param`` files and return a deduplicated,
    sorted list of model descriptors.

    Each descriptor is a dict with keys:

    - ``name``          — base name (passed to the ``-n`` CLI flag)
    - ``display_name``  — human-readable label for the UI
    - ``max_scale``     — maximum detected scale factor (defaults to ``4``)
    - ``description``   — short description for tooltips / dropdowns

    Returns an empty list when the directory is missing or contains no valid
    model files (never raises).
    """
    if not os.path.isdir(models_dir):
        return []

    # Matches a trailing ``-x<N>`` scale suffix (e.g. ``-x2``, ``-x4``).
    _SCALE_RE = re.compile(r"^(.*?)-x(\d+)$")

    # base_name → {"max_scale": int | None}
    gathered: dict[str, dict] = {}

    for entry in sorted(os.listdir(models_dir)):
        if not entry.endswith(".param"):
            continue

        stem = entry[:-6]  # strip ``.param`` (6 chars)
        m = _SCALE_RE.match(stem)

        if m:
            base_name = m.group(1)
            scale = int(m.group(2))
        else:
            base_name = stem
            scale = None

        if base_name not in gathered:
            gathered[base_name] = {"max_scale": scale}
        elif scale is not None:
            prev = gathered[base_name]["max_scale"]
            if prev is None or scale > prev:
                gathered[base_name]["max_scale"] = scale

    result = []
    for name in sorted(gathered):
        info = gathered[name]
        max_scale = info["max_scale"] if info["max_scale"] is not None else 4
        result.append({
            "name": name,
            "display_name": _infer_display_name(name),
            "max_scale": max_scale,
            "description": _infer_description(name, max_scale),
        })

    return result
