"""Tests for :mod:`models` — model auto-detection from the filesystem.

No binaries are involved; only file-system scanning is tested.
"""

import os

import pytest


def test_models_detection(project_root):
    """Detect all known models in ``script/models/``.

    Verifies that the 5 ``.param`` files are deduplicated into at least
    3 models with the expected names.
    """
    from models import get_available_models  # noqa: PLC0415

    models_dir = os.path.join(project_root, 'script', 'models')
    models = get_available_models(models_dir)

    assert len(models) >= 3
    names = [m['name'] for m in models]

    assert 'realesr-animevideov3' in names
    assert 'realesrgan-x4plus' in names
    assert 'realesrgan-x4plus-anime' in names


def test_models_max_scale(project_root):
    """The deduplicated models have correct ``max_scale`` values."""
    from models import get_available_models  # noqa: PLC0415

    models_dir = os.path.join(project_root, 'script', 'models')
    models = get_available_models(models_dir)
    by_name = {m['name']: m for m in models}

    # realesr-animevideov3 has -x2, -x3, -x4 → max_scale should be 4
    assert by_name['realesr-animevideov3']['max_scale'] == 4

    # realesrgan-x4plus has only -x4plus (no numeric suffix in regex) → default 4
    assert by_name['realesrgan-x4plus']['max_scale'] == 4


def test_models_display_names(project_root):
    """Known models should have human-readable ``display_name`` values."""
    from models import get_available_models  # noqa: PLC0415

    models_dir = os.path.join(project_root, 'script', 'models')
    models = get_available_models(models_dir)
    by_name = {m['name']: m for m in models}

    assert by_name['realesr-animevideov3']['display_name'] == 'RealESRGAN AnimeVideo v3'
    assert by_name['realesrgan-x4plus']['display_name'] == 'R-ESRGAN 4x+'


def test_models_empty_dir(tmp_dir):
    """An existing directory without ``.param`` files returns an empty list."""
    from models import get_available_models  # noqa: PLC0415

    models = get_available_models(tmp_dir)
    assert len(models) == 0


def test_models_missing_dir():
    """A non-existent directory returns an empty list (never raises)."""
    from models import get_available_models  # noqa: PLC0415

    models = get_available_models('/nonexistent/path/that/does/not/exist')
    assert len(models) == 0
