"""Tests for :mod:`resizer` — ``ImageResizer`` with real ffmpeg binary."""

import os

from PIL import Image
import pytest


# ═══════════════════════════════════════════════════════════════════════════
# resize — exact dimensions
# ═══════════════════════════════════════════════════════════════════════════


def test_resize_exact_dimensions(resizer, test_img, tmp_dir):
    """Resize to exact dimensions produces correctly-sized output."""
    out = os.path.join(tmp_dir, 'rs_exact.png')
    result = resizer.resize(test_img, out, width=800, height=600)
    assert result['success'], f"Resize failed: {result.get('error')}"
    assert os.path.isfile(out)
    with Image.open(out) as img:
        assert img.size == (800, 600), f"Expected 800x600, got {img.size}"


def test_resize_smaller(resizer, test_img, tmp_dir):
    """Resize to smaller dimensions."""
    out = os.path.join(tmp_dir, 'rs_small.png')
    result = resizer.resize(test_img, out, width=50, height=50)
    assert result['success'], f"Resize failed: {result.get('error')}"
    with Image.open(out) as img:
        assert img.size == (50, 50), f"Expected 50x50, got {img.size}"


# ═══════════════════════════════════════════════════════════════════════════
# resize_by_scale
# ═══════════════════════════════════════════════════════════════════════════


def test_resize_by_scale_2x(resizer, test_img, tmp_dir):
    """Resize by 2x factor doubles dimensions."""
    out = os.path.join(tmp_dir, 'rs_2x.png')

    # Read original dimensions
    with Image.open(test_img) as img:
        orig_w, orig_h = img.size

    result = resizer.resize_by_scale(test_img, out, scale=2.0)
    assert result['success'], f"Resize by scale failed: {result.get('error')}"

    with Image.open(out) as img:
        assert img.size == (orig_w * 2, orig_h * 2), \
            f"Expected {orig_w*2}x{orig_h*2}, got {img.size}"


def test_resize_by_scale_half(resizer, test_img, tmp_dir):
    """Resize by 0.5 factor halves dimensions (downscale)."""
    out = os.path.join(tmp_dir, 'rs_half.png')

    with Image.open(test_img) as img:
        orig_w, orig_h = img.size

    result = resizer.resize_by_scale(test_img, out, scale=0.5)
    assert result['success'], f"Resize by scale 0.5 failed: {result.get('error')}"

    with Image.open(out) as img:
        assert img.size == (max(1, orig_w // 2), max(1, orig_h // 2)), \
            f"Expected ~{orig_w//2}x~{orig_h//2}, got {img.size}"


def test_resize_by_scale_fractional(resizer, test_img, tmp_dir):
    """Resize by fractional scale (e.g. 1.5x)."""
    out = os.path.join(tmp_dir, 'rs_1.5x.png')

    with Image.open(test_img) as img:
        orig_w, orig_h = img.size

    result = resizer.resize_by_scale(test_img, out, scale=1.5)
    assert result['success'], f"Resize by fractional scale failed: {result.get('error')}"

    with Image.open(out) as img:
        assert img.size == (round(orig_w * 1.5), round(orig_h * 1.5)), \
            f"Expected {round(orig_w*1.5)}x{round(orig_h*1.5)}, got {img.size}"


# ═══════════════════════════════════════════════════════════════════════════
# Error handling
# ═══════════════════════════════════════════════════════════════════════════


def test_resize_missing_input(resizer, tmp_dir):
    """Missing input file returns error."""
    out = os.path.join(tmp_dir, 'rs_missing.png')
    result = resizer.resize('nonexistent_file.jpg', out, width=100, height=100)
    assert not result['success']
    assert 'error' in result
    assert 'not found' in (result.get('error') or '').lower()


# ═══════════════════════════════════════════════════════════════════════════
# crop
# ═══════════════════════════════════════════════════════════════════════════


def test_crop_exact(resizer, test_img, tmp_dir):
    """Center crop to specified dimensions."""
    out = os.path.join(tmp_dir, 'rs_crop.png')
    result = resizer.crop(test_img, out, width=100, height=100)
    assert result['success'], f"Crop failed: {result.get('error')}"

    with Image.open(out) as img:
        assert img.size == (100, 100), f"Expected 100x100, got {img.size}"


def test_crop_missing_input(resizer, tmp_dir):
    """Crop with missing input returns error."""
    out = os.path.join(tmp_dir, 'rs_crop_missing.png')
    result = resizer.crop('nonexistent.jpg', out, width=100, height=100)
    assert not result['success']
    assert 'not found' in (result.get('error') or '').lower()
