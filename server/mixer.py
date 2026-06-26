"""ImageMixer — wraps ffmpeg blend filter for mixing two upscaled images."""

import os
import sys
import subprocess
import shutil

from PIL import Image


class ImageMixer:
    """Blend two images together using ffmpeg's blend filter.

    For ratio=0.0 or ratio=1.0, skips ffmpeg entirely and copies the
    appropriate input file (pure pass-through).
    """

    def __init__(self, ffmpeg_path: str):
        """Initialise mixer.

        Args:
            ffmpeg_path: Path to ffmpeg.exe.

        Raises:
            FileNotFoundError: If *ffmpeg_path* does not exist.
        """
        self._ffmpeg_path = self._resolve_path(ffmpeg_path)

        if not os.path.isfile(self._ffmpeg_path):
            raise FileNotFoundError(
                f"ffmpeg not found: {self._ffmpeg_path}"
            )

    # ------------------------------------------------------------------
    # Path resolution (same pattern as engine.py)
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_base_path() -> str:
        """Return the root directory for resolving relative paths.

        - PyInstaller frozen exe → directory containing the executable.
        - Development / plain Python → current working directory.
        """
        if getattr(sys, "frozen", False):
            return os.path.dirname(os.path.realpath(sys.executable))
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

    def blend(
        self,
        image_a: str,
        image_b: str,
        output_path: str,
        ratio: float = 0.5,
    ) -> dict:
        """Blend two images using ffmpeg overlay blend.

        Args:
            image_a:     First (base) image path.
            image_b:     Second (overlay) image path.
            output_path: Destination image path.
            ratio:       Blend ratio (0.0 = all *image_a*, 1.0 = all *image_b*).

        Returns:
            dict with keys:

            * **success** (``bool``) — ``True`` if the blend succeeded.
            * **output_path** (``str``) — The resolved output path.
            * **error** (``str`` or ``None``) — Error message on failure.
        """
        abs_a = self._resolve_path(image_a)
        abs_b = self._resolve_path(image_b)
        abs_output = self._resolve_path(output_path)

        # --- Validate inputs --------------------------------------------------
        if not os.path.isfile(abs_a):
            return {
                "success": False,
                "output_path": abs_output,
                "error": f"Input A not found: {abs_a}",
            }
        if not os.path.isfile(abs_b):
            return {
                "success": False,
                "output_path": abs_output,
                "error": f"Input B not found: {abs_b}",
            }

        # --- Ratio extremes → simple file copy (no ffmpeg needed) -------------
        if ratio <= 0.0:
            try:
                shutil.copy2(abs_a, abs_output)
                return {"success": True, "output_path": abs_output, "error": None}
            except Exception as e:
                return {"success": False, "output_path": abs_output, "error": str(e)}

        if ratio >= 1.0:
            try:
                shutil.copy2(abs_b, abs_output)
                return {"success": True, "output_path": abs_output, "error": None}
            except Exception as e:
                return {"success": False, "output_path": abs_output, "error": str(e)}

        # --- Determine input image dimensions ---------------------------------
        try:
            with Image.open(abs_a) as img:
                w_a, h_a = img.size
            with Image.open(abs_b) as img:
                w_b, h_b = img.size
        except Exception as e:
            return {
                "success": False,
                "output_path": abs_output,
                "error": f"Failed to read image dimensions: {e}",
            }

        # --- Build ffmpeg filter graph ----------------------------------------

        # Clamp ratio just to be safe
        ratio_clamped = max(0.0, min(1.0, ratio))

        if (w_a, h_a) == (w_b, h_b):
            # Same dimensions → direct blend
            filter_complex = (
                f"[0:v][1:v]blend=all_mode=overlay:all_opacity={ratio_clamped}"
            )
        else:
            # Different dimensions → scale image_b to match image_a,
            # preserving aspect ratio with padding
            filter_complex = (
                f"[1:v]scale={w_a}:{h_a}:force_original_aspect_ratio=decrease,"
                f"pad={w_a}:{h_a}:(ow-iw)/2:(oh-ih)/2[1s];"
                f"[0:v][1s]blend=all_mode=overlay:all_opacity={ratio_clamped}"
            )

        args = [
            self._ffmpeg_path,
            "-i",
            abs_a,
            "-i",
            abs_b,
            "-filter_complex",
            filter_complex,
            "-y",
            abs_output,
        ]

        # --- Execute ffmpeg ---------------------------------------------------
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
