"""pytest fixtures for SD Enhance server tests.

All tests run against the real bundled binaries (realesrgan-ncnn-vulkan.exe,
ffmpeg.exe) — no mocking is used anywhere.
"""

import io
import os
import struct
import sys
import zlib

from PIL import Image
import pytest

# ── Path setup ──────────────────────────────────────────────────────────
# tests/ → server/ → project root
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(TESTS_DIR)
PROJECT_ROOT = os.path.dirname(SERVER_DIR)

# Ensure server/ is importable
sys.path.insert(0, SERVER_DIR)

# Ensure TMP/ exists
TMP_DIR = os.path.join(PROJECT_ROOT, 'TMP')
os.makedirs(TMP_DIR, exist_ok=True)

# Enable file logging so tests also write logs/sd-enhance.log
from logutil import setup_logging  # noqa: E402
setup_logging(PROJECT_ROOT)


# ── Session-scoped fixtures (reused across all tests) ──────────────────


@pytest.fixture(scope='session')
def project_root() -> str:
    """Absolute path to the project root (E:\\RE4x)."""
    return PROJECT_ROOT


@pytest.fixture(scope='session')
def tmp_dir() -> str:
    """Absolute path to the TMP/ directory."""
    return TMP_DIR


@pytest.fixture(scope='session')
def test_img() -> str:
    """Path to ``test-data/input.jpg`` (220×220 RGB)."""
    return os.path.join(PROJECT_ROOT, 'test-data', 'input.jpg')


@pytest.fixture(scope='session')
def test_img2() -> str:
    """Path to ``test-data/input2.jpg`` (256×256 RGB)."""
    return os.path.join(PROJECT_ROOT, 'test-data', 'input2.jpg')


@pytest.fixture(scope='session')
def engine():
    """Fully initialised :class:`UpscaleEngine` backed by the real
    ``realesrgan-ncnn-vulkan.exe`` binary."""
    from engine import UpscaleEngine  # noqa: PLC0415

    engine_path = os.path.join(PROJECT_ROOT, 'tools', 'realesrgan-ncnn-vulkan.exe')
    models_dir = os.path.join(PROJECT_ROOT, 'tools', 'models')
    return UpscaleEngine(engine_path, models_dir)


@pytest.fixture(scope='session')
def mixer():
    """Fully initialised :class:`ImageMixer` backed by the real
    ``ffmpeg.exe`` binary."""
    from mixer import ImageMixer  # noqa: PLC0415

    ffmpeg_path = os.path.join(PROJECT_ROOT, 'tools', 'ffmpeg.exe')
    return ImageMixer(ffmpeg_path)


@pytest.fixture(scope='session')
def resizer():
    """Fully initialised :class:`ImageResizer` backed by the real
    ``ffmpeg.exe`` binary."""
    from resizer import ImageResizer  # noqa: PLC0415

    ffmpeg_path = os.path.join(PROJECT_ROOT, 'tools', 'ffmpeg.exe')
    return ImageResizer(ffmpeg_path)


# ── Function-scoped fixtures ───────────────────────────────────────────


@pytest.fixture(scope='session')
def service(engine, mixer, resizer, project_root):
    """Fully initialised :class:`UpscaleService` for the desktop GUI.

    Backed by the real binaries; points at the real ``tools/models/``.
    """
    from core import UpscaleService  # noqa: PLC0415

    return UpscaleService(
        engine, mixer, resizer,
        models_dir=os.path.join(project_root, 'tools', 'models'),
        base_path=project_root,
    )


@pytest.fixture
def make_image():
    """Factory fixture — returns a callable that creates an in-memory
    image as a ``BytesIO`` object.

    Examples::

        buf = make_image()                         # 100×100 red JPEG
        buf = make_image((64, 64), color='blue')   # 64×64 blue JPEG
        buf = make_image(fmt='PNG')                # 100×100 red PNG
    """
    def _make(size=(100, 100), color='red', fmt='JPEG'):
        img = Image.new('RGB', size, color=color)
        buf = io.BytesIO()
        img.save(buf, format=fmt)
        buf.seek(0)
        return buf
    return _make


@pytest.fixture
def make_huge_png():
    """Factory fixture — oversized solid-colour PNG **bytes** (1 bit/pixel).

    Builds a real PNG whose pixel count is past Pillow's default
    decompression-bomb limit (``2 x 89,478,485 = 178,956,970`` px) without
    allocating a multi-hundred-MB bitmap: the tests under it only read
    dimensions, and ``Image.open()`` needs nothing but the IHDR header — the
    solid-colour IDAT stream compresses to a few KB.

    Examples::

        path.write_bytes(make_huge_png())              # 24000x8000
        path.write_bytes(make_huge_png((30000, 20000)))
    """
    def _chunk(tag, payload):
        return (struct.pack('>I', len(payload)) + tag + payload
                + struct.pack('>I', zlib.crc32(tag + payload) & 0xFFFFFFFF))

    def _make(size=(24000, 8000)):
        width, height = size
        ihdr = struct.pack('>IIBBBBB', width, height, 1, 0, 0, 0, 0)
        raw = b''.join(b'\x00' + bytes((width + 7) // 8) for _ in range(height))
        return (b'\x89PNG\r\n\x1a\n'
                + _chunk(b'IHDR', ihdr)
                + _chunk(b'IDAT', zlib.compress(raw, 9))
                + _chunk(b'IEND', b''))

    return _make
