"""Tests for :mod:`mixer` — ``ImageMixer`` with real ffmpeg binary.

All blend operations use the actual ``ffmpeg.exe`` bundled in ``tools/``.
"""

import os

import pytest


def test_mixer_blend_half(mixer, test_img, test_img2, tmp_dir):
    """Blending two images at ratio=0.5 produces a valid output file."""
    out = os.path.join(tmp_dir, 'tm_half.png')
    result = mixer.blend(test_img, test_img2, out, ratio=0.5)

    assert result['success'], f"Mixer failed: {result.get('error')}"
    assert os.path.isfile(out), 'Output file was not created'
    assert os.path.getsize(out) > 1000, 'Output file is too small'


def test_mixer_blend_zero(mixer, test_img, test_img2, tmp_dir):
    """Blending at ratio=0.0 is equivalent to a copy of image_a.

    The mixer should skip ffmpeg and use ``shutil.copy2`` instead.
    """
    out = os.path.join(tmp_dir, 'tm_zero.png')
    result = mixer.blend(test_img, test_img2, out, ratio=0.0)

    assert result['success'], f"Mixer failed: {result.get('error')}"
    assert os.path.isfile(out), 'Output file was not created'


def test_mixer_blend_one(mixer, test_img, test_img2, tmp_dir):
    """Blending at ratio=1.0 is equivalent to a copy of image_b."""
    out = os.path.join(tmp_dir, 'tm_one.png')
    result = mixer.blend(test_img, test_img2, out, ratio=1.0)

    assert result['success'], f"Mixer failed: {result.get('error')}"
    assert os.path.isfile(out), 'Output file was not created'


def test_mixer_missing_input_a(mixer, test_img2, tmp_dir):
    """Mixer returns an error when the first input does not exist."""
    out = os.path.join(tmp_dir, 'tm_bad_a.png')
    result = mixer.blend('nonexistent_file_xyz.jpg', test_img2, out, ratio=0.5)

    assert not result['success']
    assert result['error'] is not None
    assert 'not found' in result['error'].lower()


def test_mixer_missing_input_b(mixer, test_img, tmp_dir):
    """Mixer returns an error when the second input does not exist."""
    out = os.path.join(tmp_dir, 'tm_bad_b.png')
    result = mixer.blend(test_img, 'nonexistent_file_xyz.jpg', out, ratio=0.5)

    assert not result['success']
    assert result['error'] is not None
    assert 'not found' in result['error'].lower()
