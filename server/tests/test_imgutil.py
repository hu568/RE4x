"""Tests for :mod:`imgutil` — reading dimensions of oversized sources.

Background: Pillow defaults to ``MAX_IMAGE_PIXELS = 89,478,485`` and raises
``DecompressionBombError`` past ``2 x`` that (178,956,970 px), which made
``Image.open()`` fail before ``.size`` was ever read — the GUI surfaced it as
"Failed to read input dimensions: Image size (...) exceeds limit of ...".

Upscaling oversized sources is the whole point of this tool, and the pipeline
only reads dimensions with Pillow (pixels go to realesrgan-ncnn-vulkan.exe /
ffmpeg), so :mod:`imgutil` opts out of the bomb guard.
"""

from PIL import Image
import pytest

from imgutil import read_image_size

_HUGE_SIZE = (24000, 8000)          # 192,000,000 px
_PILLOW_DEFAULT_MAX = 89478485      # Pillow's default MAX_IMAGE_PIXELS


def test_pillow_pixel_limit_disabled():
    """imgutil disables Pillow's pixel limit (None = no limit)."""
    assert Image.MAX_IMAGE_PIXELS is None


def test_read_image_size_beyond_pillow_limit(make_huge_png, tmp_path):
    """Dimensions of a source past Pillow's default limit are readable."""
    src = tmp_path / 'huge.png'
    src.write_bytes(make_huge_png(_HUGE_SIZE))

    assert _HUGE_SIZE[0] * _HUGE_SIZE[1] > 2 * _PILLOW_DEFAULT_MAX
    assert read_image_size(str(src)) == _HUGE_SIZE


def test_pillow_default_limit_still_guards(make_huge_png, tmp_path, monkeypatch):
    """Guard: the same file is rejected once Pillow's default limit is back.

    Proves the regression test above is not vacuous — the crafted PNG really
    crosses the threshold.
    """
    src = tmp_path / 'huge.png'
    src.write_bytes(make_huge_png(_HUGE_SIZE))

    monkeypatch.setattr(Image, 'MAX_IMAGE_PIXELS', _PILLOW_DEFAULT_MAX)
    with pytest.raises(Image.DecompressionBombError):
        read_image_size(str(src))
