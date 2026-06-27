"""Tests for :mod:`engine` — ``UpscaleEngine`` with real binary.

Every test exercises the actual ``realesrgan-ncnn-vulkan.exe``; there are
no mocks or stubs.
"""

import os

import pytest


def test_engine_upscale_2x(engine, test_img, tmp_dir):
    """Basic 2× upscale produces a valid output file."""
    out = os.path.join(tmp_dir, 'te_out_2x.png')
    result = engine.upscale(test_img, out, scale=2)

    assert result['success'], f"Engine failed: {result.get('error')}"
    assert result['output_path'] == out
    assert os.path.isfile(out), 'Output file was not created'
    assert os.path.getsize(out) > 1000, 'Output file is too small'


def test_engine_upscale_4x(engine, test_img, tmp_dir):
    """4× upscale produces an output file that is noticeably larger."""
    out = os.path.join(tmp_dir, 'te_out_4x.png')
    result = engine.upscale(test_img, out, scale=4)

    assert result['success'], f"Engine failed: {result.get('error')}"
    assert os.path.isfile(out), 'Output file was not created'
    assert os.path.getsize(out) > 1000, 'Output file is too small'


def test_engine_upscale_with_output_format_jpg(engine, test_img, tmp_dir):
    """Engine can produce JPEG output when ``output_format='jpg'``."""
    out = os.path.join(tmp_dir, 'te_out_fmt.jpg')
    result = engine.upscale(test_img, out, scale=2, output_format='jpg')

    assert result['success'], f"Engine failed: {result.get('error')}"
    assert os.path.isfile(out), 'Output file was not created'
    assert out.lower().endswith('.jpg')


def test_engine_upscale_with_tile_size(engine, test_img, tmp_dir):
    """Engine accepts an explicit tile-size parameter."""
    out = os.path.join(tmp_dir, 'te_out_tile.png')
    result = engine.upscale(test_img, out, scale=2, tile_size=128)

    assert result['success'], f"Engine failed: {result.get('error')}"
    assert os.path.isfile(out), 'Output file was not created'


def test_engine_missing_input(engine, tmp_dir):
    """Engine returns an error dict (not an exception) for missing input."""
    out = os.path.join(tmp_dir, 'te_none.png')
    result = engine.upscale('nonexistent_file_xyz.png', out)

    assert not result['success']
    assert result['error'] is not None
    assert 'not found' in result['error'].lower()


def test_engine_bad_model(engine, test_img, tmp_dir):
    """Engine returns an error dict for an invalid/unrecognised model name."""
    out = os.path.join(tmp_dir, 'te_bad.png')
    result = engine.upscale(test_img, out, model='this_model_does_not_exist')

    assert not result['success']
    assert result['error'] is not None


def test_engine_upscale_dir(engine, test_img, test_img2, tmp_dir):
    """Engine.upscale_dir processes a directory of images in one call."""
    import shutil
    # Create a temp dir with test images
    in_dir = os.path.join(tmp_dir, 'te_dir_in')
    out_dir = os.path.join(tmp_dir, 'te_dir_out')
    os.makedirs(in_dir, exist_ok=True)
    shutil.copy2(test_img, os.path.join(in_dir, 'img1.jpg'))
    shutil.copy2(test_img2, os.path.join(in_dir, 'img2.jpg'))

    result = engine.upscale_dir(
        in_dir, out_dir, model='realesr-animevideov3', scale=2, output_format='jpg',
    )
    assert result['success'], f'upscale_dir failed: {result.get("error")}'
    assert os.path.isdir(out_dir)
    # Should have produced output files
    out_files = os.listdir(out_dir)
    assert len(out_files) >= 2, f'Expected >= 2 output files, got {len(out_files)}'


def test_engine_upscale_dir_missing(engine, tmp_dir):
    """Engine.upscale_dir with missing input returns error."""
    out_dir = os.path.join(tmp_dir, 'te_dir_out2')
    result = engine.upscale_dir('/nonexistent/dir', out_dir)
    assert not result['success']
    assert 'not found' in (result.get('error') or '').lower()
