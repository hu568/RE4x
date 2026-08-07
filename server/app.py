"""SD Enhance — pywebview desktop entry point.

Replaces the old Flask server (``main.py`` + ``routes.py``): instead of
serving a Web UI over HTTP, it opens a native desktop window rendering
``ui/index.html`` and bridges JS calls to Python via ``GuiApi``.

Path resolution:
    - Frozen exe sits at the project root, next to ``tools/``.
    - Development (``python app.py``) → project root derived from this file.
"""

import ctypes
import os
import sys

import webview

from core import UpscaleService
from engine import UpscaleEngine
from gui_api import GuiApi
from logutil import setup_logging, logger
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
    """Project root (holds ``tools/``).

    - Frozen exe sits at the project root (next to ``tools/``).
    - Dev: derived from this file's location (works from any cwd).
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.realpath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ensure_dotnet() -> None:
    """Verify the pythonnet (.NET) bridge loads before starting the GUI.

    pywebview hosts its window in WinForms via pythonnet (clr_loader).
    If the .NET Framework is missing/too old — or the bundled
    ``Python.Runtime.dll`` fails to load — ``webview.start()`` crashes with
    an obscure traceback (``Failed to resolve Python.Runtime.Loader.Initialize``).
    Detect it up front and show a clear, actionable message instead.
    """
    def _netfx_release() -> int:
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full',
            ) as key:
                return int(winreg.QueryValueEx(key, 'Release')[0])
        except Exception:
            return 0

    def _fail(detail: str) -> None:
        logger.error('pythonnet/.NET init failed: %s', detail)
        msg = (
            'SD Enhance 无法启动：缺少 .NET Framework 组件。\n\n'
            f'详情：{detail}\n\n'
            '需要 .NET Framework 4.7.2 或更高版本'
            '（Windows 10/11 通常已自带）。\n'
            '如缺失请安装 .NET Framework 4.8：\n'
            'https://dotnet.microsoft.com/download/dotnet-framework/net48\n\n'
            '安装完成后重新打开 sd-enhance-server.exe。'
        )
        try:
            ctypes.windll.user32.MessageBoxW(
                0, msg, 'SD Enhance', 0x10)  # MB_ICONERROR
        except Exception:
            pass
        sys.exit(1)

    # .NET Framework 4.7.2+ is required to load .NET Standard 2.0 assemblies.
    release = _netfx_release()
    logger.info('.NET Framework release: %s', release or 'not found')
    if release and release < 461808:  # 461808 == .NET Framework 4.7.2
        _fail(f'.NET Framework 版本过低（Release {release}，需要 4.7.2+）')

    # Pre-load pythonnet. Failures are usually transient (AV/file lock right
    # after unzip) OR netfx-specific — pywebview itself falls back to the
    # coreclr runtime when netfx fails, so mirror that here instead of
    # aborting. Each runtime gets one retry for transient lockups.
    import time

    def _try_clr() -> tuple[bool, str]:
        last_err = ''
        for attempt in (1, 2):
            try:
                import clr  # noqa: F401  # pre-load pythonnet; webview reuses it
                return True, ''
            except Exception as e:  # noqa: BLE001
                last_err = f'{type(e).__name__}: {e}'
                logger.warning('pythonnet import failed (attempt %d/2): %s',
                               attempt, last_err)
                if attempt == 1:
                    time.sleep(2)  # let AV scan / file lock release
        return False, last_err

    ok, err = _try_clr()
    if not ok:
        # netfx exhausted → switch to coreclr (like webview/winforms.py)
        logger.warning('netfx failed, falling back to coreclr')
        os.environ['PYTHONNET_RUNTIME'] = 'coreclr'
        ok, err = _try_clr()
    if not ok:
        _fail(err)

    logger.info('pythonnet OK')


def main() -> None:
    base = _base_path()
    tools = os.path.join(base, 'tools')

    log_file = setup_logging(base)
    logger.info('=== SD Enhance %s starting ===', 'frozen' if getattr(sys, 'frozen', False) else 'dev')
    logger.info('project root: %s', base)
    logger.info('log file: %s', log_file)

    _ensure_dotnet()

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
