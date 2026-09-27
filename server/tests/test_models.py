"""Tests for :mod:`models` — model auto-detection from the filesystem.

No binaries are involved; only file-system scanning is tested.
"""

import os

import pytest


def test_models_detection(project_root):
    """Detect all known models in ``tools/models/``.

    Verifies that the shipped ``.param`` files are deduplicated into the
    expected models (animevideov3 was removed from the distro in v2.0).
    """
    from models import get_available_models  # noqa: PLC0415

    models_dir = os.path.join(project_root, 'tools', 'models')
    models = get_available_models(models_dir)

    assert len(models) >= 3
    names = [m['name'] for m in models]

    assert 'realesrgan-x4plus' in names
    assert 'realesrgan-x4plus-anime' in names
    assert 'spanv2' in names


def test_models_max_scale(project_root):
    """The deduplicated models have correct ``max_scale`` values."""
    from models import get_available_models  # noqa: PLC0415

    models_dir = os.path.join(project_root, 'tools', 'models')
    models = get_available_models(models_dir)
    by_name = {m['name']: m for m in models}

    # realesrgan-x4plus / -x4plus-anime / spanv2 have no numeric suffix → default 4
    assert by_name['realesrgan-x4plus']['max_scale'] == 4
    assert by_name['realesrgan-x4plus-anime']['max_scale'] == 4
    assert by_name['spanv2']['max_scale'] == 4


def test_models_display_names(project_root):
    """Known models should have human-readable ``display_name`` values."""
    from models import get_available_models  # noqa: PLC0415

    models_dir = os.path.join(project_root, 'tools', 'models')
    models = get_available_models(models_dir)
    by_name = {m['name']: m for m in models}

    assert by_name['realesrgan-x4plus']['display_name'] == 'R-ESRGAN 4x+'
    assert by_name['realesrgan-x4plus-anime']['display_name'] == 'R-ESRGAN 4x+ Anime'
    assert by_name['spanv2']['display_name'] == 'SPANV2 (NTIRE2026)'


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


# ── resolve_model_param: base name → on-disk .param stem ─────────────────


def test_resolve_model_param_exact(tmp_path):
    """An exact ``<name>.param`` wins (spanv2 has no scale variants)."""
    from models import resolve_model_param  # noqa: PLC0415

    (tmp_path / 'spanv2.param').write_bytes(b'')
    (tmp_path / 'spanv2.bin').write_bytes(b'')
    assert resolve_model_param(str(tmp_path), 'spanv2') == 'spanv2'


def test_resolve_model_param_scale_variant(tmp_path):
    """Collapsed base name resolves to the -x4 variant.

    Regression (black video output): the GUI submits ``realesr-animevideov3``
    while the shipped files are ``realesr-animevideov3-x2/-x3/-x4`` — the
    bare base name loads nothing in the engine / realesrgan filter.
    """
    from models import resolve_model_param  # noqa: PLC0415

    for name in ('realesr-animevideov3-x2.param',
                 'realesr-animevideov3-x3.param',
                 'realesr-animevideov3-x4.param',
                 'realesr-animevideov3-x4.bin'):
        (tmp_path / name).write_bytes(b'')
    assert (resolve_model_param(str(tmp_path), 'realesr-animevideov3')
            == 'realesr-animevideov3-x4')


def test_resolve_model_param_no_x4_prefers_highest(tmp_path):
    """Without a -x4 file the highest available scale variant is used."""
    from models import resolve_model_param  # noqa: PLC0415

    for name in ('mymodel-x2.param', 'mymodel-x3.param'):
        (tmp_path / name).write_bytes(b'')
    assert resolve_model_param(str(tmp_path), 'mymodel') == 'mymodel-x3'


def test_resolve_model_param_missing(tmp_path):
    """No matching file (or missing directory) resolves to None."""
    from models import resolve_model_param  # noqa: PLC0415

    (tmp_path / 'other.param').write_bytes(b'')
    assert resolve_model_param(str(tmp_path), 'nope') is None
    assert resolve_model_param(str(tmp_path / 'void'), 'nope') is None
