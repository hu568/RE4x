# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the SD Enhance desktop GUI (pywebview).
# Build:
#   .venv\Scripts\pyinstaller build.spec --distpath ..\tools\sd-enhance-server --workpath ..\tools\build --clean
# Output goes to tools/sd-enhance-server/ (see package_release.py).

import os

from PyInstaller.utils.hooks import collect_all

# Resolve the spec directory (server/) so pathex works on any machine.
_SPEC_DIR = os.path.dirname(os.path.abspath(SPECPATH))

# pywebview (Windows edgechromium) needs its data + pythonnet/clr_loader runtimes.
pywebview_datas, pywebview_binaries, pywebview_hidden = collect_all('pywebview')
clr_datas, clr_binaries, clr_hidden = collect_all('clr_loader')
pynet_datas, pynet_binaries, pynet_hidden = collect_all('pythonnet')

a = Analysis(
    ['app.py'],
    pathex=[_SPEC_DIR],
    binaries=pywebview_binaries + clr_binaries + pynet_binaries,
    datas=[('ui', 'ui')] + pywebview_datas + clr_datas + pynet_datas,  # Bundle ui/
    hiddenimports=[
        'engine', 'mixer', 'resizer', 'models', 'core', 'gui_api',
    ] + pywebview_hidden + clr_hidden + pynet_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'flask', 'werkzeug', 'jinja2', 'itsdangerous', 'click', 'blinker',
        'tkinter', 'PyQt5', 'PySide2', 'PySide6',
        'numpy', 'scipy', 'pandas', 'matplotlib',
        'cryptography', 'PIL._tkinter',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='sd-enhance-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # desktop GUI — no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='sd-enhance-server',
)
