"""Tests for :mod:`gui_api` — the pywebview JS↔Python bridge.

Only the bridge methods added for the About dialog / startup default model are
covered here; they need no binaries (``os.startfile`` is never called for real).
"""

import gui_api


def _api(service):
    return gui_api.GuiApi(service)


# ── Default model (startup pre-selection) ────────────────────────────────


def test_get_default_model_matches_installed_default(service):
    """The GUI pre-selects R-ESRGAN 4x+ Anime — the same model core falls
    back to when the frontend sends no model."""
    assert _api(service).get_default_model() == 'realesrgan-x4plus-anime'


def test_get_default_model_matches_parse_params(service):
    api = _api(service)
    assert api.get_default_model() == service.parse_params({})[0]['model']


def test_get_default_model_falls_back_when_pruned(service, monkeypatch):
    """A user who deleted the default model still gets a usable dropdown."""
    monkeypatch.setattr(service, 'get_models',
                        lambda: [{'name': 'spanv2'}])
    assert _api(service).get_default_model() == 'spanv2'


def test_get_default_model_no_models(service, monkeypatch):
    monkeypatch.setattr(service, 'get_models', lambda: [])
    assert _api(service).get_default_model() is None
