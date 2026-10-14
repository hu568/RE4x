"""Tests for :mod:`gui_api` — the pywebview JS↔Python bridge.

Only the bridge methods added for the About dialog / startup default model are
covered here; they need no binaries (``os.startfile`` is never called for real).
"""

import os

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


# ── About dialog: log location ───────────────────────────────────────────


def test_get_log_rel_path_is_relative(service):
    """The About dialog must never show an absolute install path."""
    rel = _api(service).get_log_rel_path()

    assert rel == os.path.join('logs', 'sd-enhance.log')
    assert not os.path.isabs(rel)
    assert service.base_path not in rel


def test_get_log_rel_path_has_no_legacy_absolute_api(service):
    """The old absolute-path bridge method is gone, not just unused."""
    assert not hasattr(_api(service), 'get_log_path')


def test_open_log_folder_uses_absolute_path(service, monkeypatch):
    """Opening the folder still resolves the absolute path on the Python side."""
    opened = []
    monkeypatch.setattr(gui_api.os, 'startfile', opened.append)

    assert _api(service).open_log_folder() is True
    assert opened == [os.path.join(service.base_path, 'logs')]


# ── About dialog: external link ──────────────────────────────────────────


def test_open_external_https(service, monkeypatch):
    """http/https URLs are handed to the OS default browser."""
    opened = []
    monkeypatch.setattr(gui_api.os, 'startfile', opened.append)

    assert _api(service).open_external('https://github.com/hu568/RE4x') is True
    assert opened == ['https://github.com/hu568/RE4x']


def test_open_external_rejects_non_http(service, monkeypatch):
    """Anything that is not http(s) is refused before reaching the shell."""
    opened = []
    monkeypatch.setattr(gui_api.os, 'startfile', opened.append)
    api = _api(service)

    for bad in ('file:///C:/Windows/System32/cmd.exe', 'javascript:alert(1)',
                'cmd.exe', '', None, 42):
        assert api.open_external(bad) is False
    assert opened == []


def test_open_external_survives_shell_failure(service, monkeypatch):
    def boom(_url):
        raise OSError('no default handler')

    monkeypatch.setattr(gui_api.os, 'startfile', boom)
    assert _api(service).open_external('https://github.com/hu568/RE4x') is False
