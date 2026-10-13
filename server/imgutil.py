"""Pillow helpers shared by core / resizer / mixer.

``Image.MAX_IMAGE_PIXELS`` — Pillow treats images above this pixel count as
potential decompression bombs: past ``2 x MAX_IMAGE_PIXELS`` (178,956,970 px
with the default 89,478,485 px) :func:`PIL.Image.open` raises
``DecompressionBombError`` before the caller can even read ``.size``.

Upscaling oversized sources is exactly what this tool is for (22000x15000
sources are normal here), and the pipeline only ever reads dimensions with
Pillow — pixel data is handled by ``realesrgan-ncnn-vulkan.exe`` / ``ffmpeg``,
so an ``Image.open()`` never decompresses the image into RAM. The limit is
therefore disabled globally on import of this module.
"""

from PIL import Image

# None = no limit (Pillow's documented way to opt out of the bomb guard).
Image.MAX_IMAGE_PIXELS = None


def read_image_size(path: str) -> tuple[int, int]:
    """Return ``(width, height)`` of *path* without decoding pixel data."""
    with Image.open(path) as img:
        return img.size
