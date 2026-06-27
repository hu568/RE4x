"""ImageResizer — wraps ffmpeg scale/crop filter for the second step of upscale pipeline.

Model always upscales at 4x; this module resizes the 4x output to the
final target dimensions or scale factor.
"""

import os
import sys
import subprocess

from PIL import Image


class ImageResizer:
    """Resize / crop images using ffmpeg's scale and crop filters.

    Uses lanczos scaling for quality.
    """

    def __init__(self, ffmpeg_path: str):
        """Initialise resizer.

        Args:
            ffmpeg_path: Path to ffmpeg.exe (absolute or relative to project root).

        Raises:
            FileNotFoundError: If *ffmpeg_path* does not exist.
        """
        self._ffmpeg_path = self._resolve_path(ffmpeg_path)

        if not os.path.isfile(self._ffmpeg_path):
            raise FileNotFoundError(
                f"ffmpeg not found: {self._ffmpeg_path}"
            )

    # ------------------------------------------------------------------
    # Path resolution (same pattern as engine.py / mixer.py)
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_base_path() -> str:
        """Return the project root directory for resolving relative paths.

        - PyInstaller frozen exe at ``tools/sd-enhance-server/``
          → walk up 2 levels to project root.
        - Development / plain Python → current working directory.
        """
        if getattr(sys, "frozen", False):
            exe_dir = os.path.dirname(os.path.realpath(sys.executable))
            return os.path.dirname(os.path.dirname(exe_dir))
        return os.getcwd()

    @classmethod
    def _resolve_path(cls, path: str) -> str:
        """Resolve *path* to an absolute, symlink-free location.

        Relative paths are anchored to :meth:`_resolve_base_path`.
        """
        if os.path.isabs(path):
            return os.path.realpath(path)
        base = cls._resolve_base_path()
        return os.path.realpath(os.path.join(base, path))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resize(
        self,
        input_path: str,
        output_path: str,
        width: int,
        height: int,
    ) -> dict:
        """Resize image to exact dimensions using ffmpeg lanczos scaling.

        Args:
            input_path:  Source image path.
            output_path: Destination image path.
            width:       Target width in pixels.
            height:      Target height in pixels.

        Returns:
            ``{"success": bool, "output_path": str, "error": str|None}``
        """
        abs_input = self._resolve_path(input_path)
        abs_output = self._resolve_path(output_path)

        if not os.path.isfile(abs_input):
            return {
                "success": False,
                "output_path": abs_output,
                "error": f"Input file not found: {abs_input}",
            }

        # Ensure output directory exists
        os.makedirs(os.path.dirname(abs_output), exist_ok=True)

        args = [
            self._ffmpeg_path,
            "-i", abs_input,
            "-vf", f"scale={width}:{height}:flags=lanczos",
            "-y",
            abs_output,
        ]

        process = None
        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
            _stdout, stderr = process.communicate(timeout=120)

            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="replace").strip()
                return {
                    "success": False,
                    "output_path": abs_output,
                    "error": error_msg
                    or f"ffmpeg exited with code {process.returncode}",
                }

            return {"success": True, "output_path": abs_output, "error": None}

        except subprocess.TimeoutExpired:
            if process is not None:
                process.kill()
                process.wait()
            return {
                "success": False,
                "output_path": abs_output,
                "error": "ffmpeg timed out after 120s",
            }
        except Exception as e:
            return {
                "success": False,
                "output_path": abs_output,
                "error": str(e),
            }

    def resize_by_scale(
        self,
        input_path: str,
        output_path: str,
        scale: float,
    ) -> dict:
        """Resize by a multiplicative scale factor.

        Reads input dimensions via PIL, multiplies by *scale*, rounds to
        integer pixels, then delegates to :meth:`resize`.

        Args:
            input_path:  Source image path.
            output_path: Destination image path.
            scale:       Scale factor (e.g. 0.5 to halve, 2.0 to double).

        Returns:
            ``{"success": bool, "output_path": str, "error": str|None}``
        """
        abs_input = self._resolve_path(input_path)

        try:
            with Image.open(abs_input) as img:
                w, h = img.size
        except Exception as e:
            return {
                "success": False,
                "output_path": self._resolve_path(output_path),
                "error": f"Failed to read input dimensions: {e}",
            }

        target_w = max(1, round(w * scale))
        target_h = max(1, round(h * scale))

        return self.resize(input_path, output_path, target_w, target_h)

    def crop(
        self,
        input_path: str,
        output_path: str,
        width: int,
        height: int,
    ) -> dict:
        """Center-crop image to exact dimensions using ffmpeg crop filter.

        Args:
            input_path:  Source image path.
            output_path: Destination image path.
            width:       Target width in pixels.
            height:      Target height in pixels.

        Returns:
            ``{"success": bool, "output_path": str, "error": str|None}``
        """
        abs_input = self._resolve_path(input_path)
        abs_output = self._resolve_path(output_path)

        if not os.path.isfile(abs_input):
            return {
                "success": False,
                "output_path": abs_output,
                "error": f"Input file not found: {abs_input}",
            }

        os.makedirs(os.path.dirname(abs_output), exist_ok=True)

        # ffmpeg crop=w:h:x:y where x,y center the crop
        args = [
            self._ffmpeg_path,
            "-i", abs_input,
            "-vf", f"crop={width}:{height}",
            "-y",
            abs_output,
        ]

        process = None
        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
            _stdout, stderr = process.communicate(timeout=120)

            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="replace").strip()
                return {
                    "success": False,
                    "output_path": abs_output,
                    "error": error_msg
                    or f"ffmpeg exited with code {process.returncode}",
                }

            return {"success": True, "output_path": abs_output, "error": None}

        except subprocess.TimeoutExpired:
            if process is not None:
                process.kill()
                process.wait()
            return {
                "success": False,
                "output_path": abs_output,
                "error": "ffmpeg timed out after 120s",
            }
        except Exception as e:
            return {
                "success": False,
                "output_path": abs_output,
                "error": str(e),
            }
