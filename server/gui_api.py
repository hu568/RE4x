"""GuiApi — pywebview JS↔Python bridge for the SD Enhance desktop GUI.

Every method here is callable from the frontend via
``window.pywebview.api.<method>(...)``. Methods that start long work return
a ``task_id`` immediately; the frontend polls
:meth:`GuiApi.get_task` for progress/results.

Native dialogs (file open / folder / save) use pywebview's
``create_file_dialog`` so the GUI stays dependency-free (no tkinter/Qt).
"""

import base64
import os
import shutil

import webview


class GuiApi:
    """Bridge object injected into the pywebview window as ``js_api``."""

    def __init__(self, service):
        self.service = service
        self._window = None

    def set_window(self, window) -> None:
        """Attach the pywebview window (needed for native dialogs)."""
        self._window = window

    # ── Native dialogs ────────────────────────────────────────────────────

    def select_files(self, multiple: bool = True):
        """Open the native file picker; returns a list of paths or None."""
        if self._window is None:
            return None
        dialog = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=bool(multiple),
            file_types=(
                'Image files (*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.tiff)',
                'All files (*.*)',
            ),
        )
        if not dialog:
            return []
        return list(dialog) if isinstance(dialog, (list, tuple)) else [dialog]

    def select_video(self):
        """Open the native file picker for videos; returns a path or None."""
        if self._window is None:
            return None
        dialog = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=(
                'Video files (*.mp4;*.webm;*.avi;*.mov;*.mkv)',
                'All files (*.*)',
            ),
        )
        return dialog[0] if dialog else None

    def select_dir(self):
        """Open the native folder picker; returns a path or None."""
        if self._window is None:
            return None
        dialog = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        return dialog[0] if dialog else None

    def save_path(self, suggested_name: str):
        """Open the native save dialog; returns a path or None."""
        if self._window is None:
            return None
        dialog = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=suggested_name or 'output.png',
        )
        return dialog[0] if dialog else None

    # ── Info ──────────────────────────────────────────────────────────────

    def get_models(self) -> list[dict]:
        return self.service.get_models()

    def image_preview(self, path: str, max_bytes: int = 512 * 1024):
        """Return a base64 data-URL preview of *path* (for <img> tags).

        Returns ``None`` when the file is missing, unreadable, or larger
        than *max_bytes* (checked before reading to avoid loading huge
        files into memory).
        """
        if not path or not os.path.isfile(path):
            return None
        try:
            if os.path.getsize(path) > max_bytes:
                return None
            with open(path, 'rb') as f:
                data = f.read()
            ext = os.path.splitext(path)[1].lower().lstrip('.')
            mime = {'jpg': 'jpeg', 'jpeg': 'jpeg'}.get(ext, ext or 'png')
            return f"data:image/{mime};base64,{base64.b64encode(data).decode('ascii')}"
        except Exception:
            return None

    # ── Tasks ─────────────────────────────────────────────────────────────

    def submit_single(self, path: str, params: dict) -> dict:
        """Start a single-image upscale task → ``{"task_id": "..."}``."""
        if not path:
            return {'error': 'No file selected'}
        return {'task_id': self.service.submit_single(path, params)}

    def submit_files(self, paths: list, params: dict) -> dict:
        """Start a multi-file upscale task → ``{"task_id": "..."}``."""
        paths = [p for p in (paths or []) if p]
        if not paths:
            return {'error': 'No files selected'}
        return {'task_id': self.service.submit_files(paths, params)}

    def submit_dir(self, input_dir: str, output_dir: str | None,
                   params: dict) -> dict:
        """Start a directory upscale task → ``{"task_id": "..."}``."""
        if not input_dir:
            return {'error': 'No input directory selected'}
        return {'task_id': self.service.submit_dir(
            input_dir, output_dir or None, params)}

    def submit_video(self, path: str, params: dict) -> dict:
        """Start a video upscale task → ``{"task_id": "..."}``."""
        if not path:
            return {'error': 'No video selected'}
        return {'task_id': self.service.submit_video(path, params)}

    def get_task(self, task_id: str) -> dict | None:
        return self.service.get_task(task_id)

    # ── Result helpers ────────────────────────────────────────────────────

    def open_path(self, path: str) -> bool:
        """Open *path* with the OS default handler (e.g. show the image)."""
        try:
            os.startfile(path)  # noqa: S606 — local GUI, intended
            return True
        except Exception:
            return False

    def open_folder(self, path: str) -> bool:
        """Open the folder containing *path* in Explorer."""
        try:
            folder = os.path.dirname(os.path.abspath(path))
            os.startfile(folder)  # noqa: S606
            return True
        except Exception:
            return False

    def copy_to(self, src: str, dest_dir: str, filename: str | None = None):
        """Copy *src* into *dest_dir* (e.g. 'Save as'). Returns dest path.

        Returns ``{"success": bool, "dest": str|None, "error": str|None}``.
        """
        try:
            if not os.path.isfile(src):
                return {'success': False, 'dest': None,
                        'error': f'Source not found: {src}'}
            os.makedirs(dest_dir, exist_ok=True)
            # basename so a crafted filename can never escape dest_dir
            name = os.path.basename(filename or os.path.basename(src))
            dest = os.path.join(dest_dir, name)
            shutil.copy2(src, dest)
            return {'success': True, 'dest': dest, 'error': None}
        except Exception as e:
            return {'success': False, 'dest': None, 'error': str(e)}

    def zip_results(self, task_id: str, dest_zip: str) -> dict:
        """Package a task's results into *dest_zip*. Returns result dict."""
        return self.service.zip_results(task_id, dest_zip)
