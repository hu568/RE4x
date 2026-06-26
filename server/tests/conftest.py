"""pytest fixtures for SD Enhance server tests.

All tests run against the real bundled binaries (realesrgan-ncnn-vulkan.exe,
ffmpeg.exe) — no mocking is used anywhere.
"""

import io
import os
import sys

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
    """Path to ``test/input.jpg`` (220×220 RGB)."""
    return os.path.join(PROJECT_ROOT, 'test', 'input.jpg')


@pytest.fixture(scope='session')
def test_img2() -> str:
    """Path to ``test/input2.jpg`` (256×256 RGB)."""
    return os.path.join(PROJECT_ROOT, 'test', 'input2.jpg')


@pytest.fixture(scope='session')
def engine():
    """Fully initialised :class:`UpscaleEngine` backed by the real
    ``realesrgan-ncnn-vulkan.exe`` binary."""
    from engine import UpscaleEngine  # noqa: PLC0415

    engine_path = os.path.join(PROJECT_ROOT, 'script', 'realesrgan-ncnn-vulkan.exe')
    models_dir = os.path.join(PROJECT_ROOT, 'script', 'models')
    return UpscaleEngine(engine_path, models_dir)


@pytest.fixture(scope='session')
def mixer():
    """Fully initialised :class:`ImageMixer` backed by the real
    ``ffmpeg.exe`` binary."""
    from mixer import ImageMixer  # noqa: PLC0415

    ffmpeg_path = os.path.join(PROJECT_ROOT, 'script', 'ffmpeg.exe')
    return ImageMixer(ffmpeg_path)


# ── Function-scoped fixtures ───────────────────────────────────────────


@pytest.fixture
def client():
    """Flask test client with real engine and mixer.

    Temporarily changes the working directory to the project root so that
    ``create_app()`` resolves ``script/`` paths correctly.

    Usage::

        def test_something(client):
            resp = client.get('/api/models')
            assert resp.status_code == 200
    """
    old_cwd = os.getcwd()
    os.chdir(PROJECT_ROOT)
    try:
        from main import create_app  # noqa: PLC0415
        app = create_app()
        app.config['TESTING'] = True
        with app.test_client() as c:
            yield c
    finally:
        os.chdir(old_cwd)


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
