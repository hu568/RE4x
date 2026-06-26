"""UpscaleEngine — wraps realesrgan-ncnn-vulkan.exe subprocess calls."""

import os
import sys
import subprocess
import threading


class UpscaleEngine:
    """AI image upscaling via realesrgan-ncnn-vulkan.exe subprocess.

    Thread-safe: uses a class-level threading.Lock to serialise all engine
    calls and prevent concurrent GPU access.
    """

    _lock = threading.Lock()

    def __init__(self, engine_path: str, models_dir: str):
        """Initialise engine wrapper.

        Args:
            engine_path: Path to realesrgan-ncnn-vulkan.exe.
            models_dir:  Path to the directory containing .param / .bin model
                         files.

        Raises:
            FileNotFoundError: If either path does not exist.
        """
        self._engine_path = self._resolve_path(engine_path)
        self._models_dir = self._resolve_path(models_dir)

        if not os.path.isfile(self._engine_path):
            raise FileNotFoundError(
                f"Engine not found: {self._engine_path}"
            )
        if not os.path.isdir(self._models_dir):
            raise FileNotFoundError(
                f"Models directory not found: {self._models_dir}"
            )

    # ------------------------------------------------------------------
    # Path resolution helpers
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

    def upscale(
        self,
        input_path: str,
        output_path: str,
        model: str = "realesr-animevideov3",
        scale: float = 2.0,
        tile_size: int = 0,
        gpu_id: int = -1,
        tta: bool = False,
        output_format: str = "png",
        timeout: int = 300,
    ) -> dict:
        """Run a single image through the upscale engine.

        Args:
            input_path:   Source image path.
            output_path:  Destination image path.
            model:        Model name (without scale suffix, e.g.
                          ``realesr-animevideov3``).
            scale:        Upscale ratio (2-4, coerced to int).
            tile_size:    Tile size in pixels (0 = auto).
            gpu_id:       GPU device index (-1 = auto).
            tta:          Enable test-time augmentation.
            output_format: Output format (``"png"`` or ``"jpg"``).
            timeout:      Subprocess timeout in seconds.

        Returns:
            dict with keys:
                * **success** (``bool``) — ``True`` if the engine exited with
                  code 0.
                * **output_path** (``str``) — The resolved output path.
                * **error** (``str`` or ``None``) — Error message on failure.
        """
        # Resolve to absolute paths
        abs_input = self._resolve_path(input_path)
        abs_output = self._resolve_path(output_path)

        # Validate input
        if not os.path.isfile(abs_input):
            return {
                "success": False,
                "output_path": abs_output,
                "error": f"Input file not found: {abs_input}",
            }

        # Build argument list -------------------------------------------------
        scale_int = int(scale)
        args = [
            self._engine_path,
            "-i",
            abs_input,
            "-o",
            abs_output,
            "-s",
            str(scale_int),
            "-n",
            model,
        ]

        if tile_size > 0:
            args.extend(["-t", str(tile_size)])
        if gpu_id >= 0:
            args.extend(["-g", str(gpu_id)])
        if tta:
            args.append("-x")
        args.extend(["-f", output_format])

        # Run subprocess ------------------------------------------------------
        with self.__class__._lock:
            process = None
            try:
                process = subprocess.Popen(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                )
                stdout, stderr = process.communicate(timeout=timeout)

                if process.returncode != 0:
                    error_msg = stderr.decode("utf-8", errors="replace").strip()
                    return {
                        "success": False,
                        "output_path": abs_output,
                        "error": error_msg
                        or f"Process exited with code {process.returncode}",
                    }

                return {
                    "success": True,
                    "output_path": abs_output,
                    "error": None,
                }

            except subprocess.TimeoutExpired:
                if process is not None:
                    process.kill()
                    process.wait()
                return {
                    "success": False,
                    "output_path": abs_output,
                    "error": f"Process timed out after {timeout}s",
                }
            except Exception as e:
                return {
                    "success": False,
                    "output_path": abs_output,
                    "error": str(e),
                }
