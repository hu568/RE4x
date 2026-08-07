"""Subprocess helpers for the SD Enhance desktop app.

On Windows, child console tools (``ffmpeg.exe``, ``realesrgan-ncnn-vulkan.exe``)
would otherwise pop up an empty console window when spawned from the GUI
process (which itself has no console, ``console=False`` in the spec).
``CREATE_NO_WINDOW`` suppresses those flashing terminal windows.

Use :func:`popen` instead of ``subprocess.Popen`` everywhere a child tool
is launched; the flag is a no-op on non-Windows platforms.
"""

import os
import subprocess

# 0x08000000 — the child process is launched without a console window.
_CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def popen(args, **kwargs):
    """``subprocess.Popen`` that never opens a console window on Windows.

    All keyword arguments are forwarded to ``subprocess.Popen``; the
    ``creationflags`` argument is OR-ed with ``CREATE_NO_WINDOW``.
    """
    if os.name == 'nt' and _CREATE_NO_WINDOW:
        flags = kwargs.pop('creationflags', 0) | _CREATE_NO_WINDOW
        kwargs['creationflags'] = flags
    return subprocess.Popen(args, **kwargs)
