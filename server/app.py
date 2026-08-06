"""SD Enhance — pywebview desktop entry point.

Replaces the old Flask server (``main.py`` + ``routes.py``): instead of
serving a Web UI over HTTP, it opens a native desktop window rendering
``ui/index.html`` and bridges JS calls to Python via ``GuiApi``.

Path resolution:
    - Frozen (PyInstaller) exe at ``tools/sd-enhance-server/``
      → project root is 2 levels up (engine/ffmpeg/models live there).
    - Development (``python app.py``) → current working directory.
"""

import os
import sys

import webview

from core import UpscaleService
from engine import UpscaleEngine
from gui_api import GuiApi
from mixer import ImageMixer
from resizer import ImageResizer


def _resource_path(rel: str) -> str:
    """Absolute path for bundled UI assets.

    - Frozen: inside the PyInstaller ``_MEIPASS`` data dir (``ui/``).
    - Dev:    alongside this file (``server/ui/``).
    """
    if getattr(sys, 'frozen', False):
        base = getattr(
            sys, '_MEIPASS',
            os.path.dirname(os.path.realpath(sys.executable)),
        )
        return os.path.join(base, rel)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)


def _base_path() -> str:
    """Project root (holds ``tools/``)."""
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(os.path.realpath(sys.executable))
        return os.path.dirname(os.path.dirname(exe_dir))
    return os.getcwd()


def main() -> None:
    base = _base_path()
    tools = os.path.join(base, 'tools')

    engine = UpscaleEngine(
        os.path.join(tools, 'realesrgan-ncnn-vulkan.exe'),
        os.path.join(tools, 'models'),
    )
    mixer = ImageMixer(os.path.join(tools, 'ffmpeg.exe'))
    resizer = ImageResizer(os.path.join(tools, 'ffmpeg.exe'))

    service = UpscaleService(
        engine, mixer, resizer,
        models_dir=os.path.join(tools, 'models'),
        base_path=base,
    )
    api = GuiApi(service)

    ui_html = _resource_path(os.path.join('ui', 'index.html'))
    window = webview.create_window(
        'SD Enhance 图片放大工具',
        ui_html,
        js_api=api,
        width=1120,
        height=780,
        min_size=(960, 640),
    )
    api.set_window(window)

    webview.start(debug=False)


if __name__ == '__main__':
    main()
