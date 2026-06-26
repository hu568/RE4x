"""Tests for :mod:`routes` — Flask API endpoints against real binaries.

Every route test uses the Flask test client (no HTTP server required) and
exercises the actual engine/mixer binaries through ``create_app()``.
"""

import io

import pytest


# ═══════════════════════════════════════════════════════════════════════
# GET /
# ═══════════════════════════════════════════════════════════════════════


def test_get_index(client):
    """``GET /`` returns the Web UI HTML page."""
    resp = client.get('/')
    assert resp.status_code == 200
    assert resp.mimetype == 'text/html'
    assert b'SD Enhance' in resp.data or b'sd-enhance' in resp.data


# ═══════════════════════════════════════════════════════════════════════
# GET /api/models
# ═══════════════════════════════════════════════════════════════════════


def test_get_models(client):
    """``GET /api/models`` returns at least 3 known models."""
    resp = client.get('/api/models')
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    assert len(data) >= 3
    names = [m['name'] for m in data]
    assert 'realesr-animevideov3' in names
    assert 'realesrgan-x4plus' in names
    assert 'realesrgan-x4plus-anime' in names


# ═══════════════════════════════════════════════════════════════════════
# POST /api/upscale  (single image, synchronous)
# ═══════════════════════════════════════════════════════════════════════


def test_upscale_single(client, make_image):
    """Upload a JPEG and receive an upscaled PNG back (single-stage)."""
    data = {
        'file': (make_image(), 'test.jpg'),
        'scale': '2',
        'model': 'realesr-animevideov3',
    }
    resp = client.post('/api/upscale', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200, f'Expected 200, got {resp.status_code}: {resp.get_json(silent=True)}'
    assert resp.mimetype == 'image/png' or resp.content_type.startswith('image/')
    assert len(resp.data) > 1000, 'Response body is too small'


def test_upscale_two_stage(client, make_image):
    """Upload a JPEG and run two-stage blend (model + model_2 + mix_ratio)."""
    data = {
        'file': (make_image(), 'test.jpg'),
        'scale': '2',
        'model': 'realesr-animevideov3',
        'model_2': 'realesrgan-x4plus',
        'mix_ratio': '0.5',
    }
    resp = client.post('/api/upscale', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200, f'Expected 200, got {resp.status_code}: {resp.get_json(silent=True)}'
    assert resp.content_type.startswith('image/')
    assert len(resp.data) > 500, 'Response body is too small'


def test_upscale_two_stage_zero_ratio(client, make_image):
    """Two-stage with mix_ratio=0.0 falls back to single-stage for image_a copy."""
    data = {
        'file': (make_image(), 'test.jpg'),
        'scale': '2',
        'model': 'realesr-animevideov3',
        'model_2': 'realesrgan-x4plus',
        'mix_ratio': '0.0',
    }
    resp = client.post('/api/upscale', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200, f'Expected 200, got {resp.status_code}: {resp.get_json(silent=True)}'


def test_upscale_no_file(client):
    """POST without a file returns 400."""
    data = {'scale': '2'}
    resp = client.post('/api/upscale', data=data, content_type='multipart/form-data')
    assert resp.status_code == 400
    body = resp.get_json()
    assert body is not None
    assert 'error' in body


def test_upscale_bad_extension(client):
    """Uploading a non-image extension (.txt) returns 400."""
    data = {'file': (io.BytesIO(b'not an image'), 'test.txt')}
    resp = client.post('/api/upscale', data=data, content_type='multipart/form-data')
    assert resp.status_code == 400
    body = resp.get_json()
    assert body is not None
    assert 'not allowed' in body['error'].lower()


def test_upscale_bad_model(client, make_image):
    """Passing an invalid model name returns 500."""
    data = {
        'file': (make_image(), 'test.jpg'),
        'model': 'this_model_does_not_exist_xyz',
    }
    resp = client.post('/api/upscale', data=data, content_type='multipart/form-data')
    assert resp.status_code == 500
    body = resp.get_json()
    assert body is not None
    assert 'error' in body


# ═══════════════════════════════════════════════════════════════════════
# POST /api/upscale/batch  (multi-file, async)
# ═══════════════════════════════════════════════════════════════════════


def test_batch_empty(client):
    """Batch with no files returns 400."""
    resp = client.post('/api/upscale/batch', content_type='multipart/form-data')
    assert resp.status_code == 400
    body = resp.get_json()
    assert body is not None
    assert 'error' in body


def test_batch_with_files(client, make_image):
    """Batch with valid files returns a task_id."""
    data = {
        'files': (make_image(), 'img1.jpg'),
        'model': 'realesr-animevideov3',
        'scale': '2',
    }
    resp = client.post('/api/upscale/batch', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body is not None
    assert 'task_id' in body
    assert len(body['task_id']) == 8  # 8-char UUID prefix


# ═══════════════════════════════════════════════════════════════════════
# POST /api/upscale/dir  (directory, async)
# ═══════════════════════════════════════════════════════════════════════


def test_dir_missing(client):
    """Directory mode with a non-existent path returns 400."""
    resp = client.post('/api/upscale/dir', json={'input_dir': '/nonexistent/path'})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body is not None
    assert 'error' in body


def test_dir_path_traversal(client):
    """Directory mode rejects a path outside the project root."""
    resp = client.post(
        '/api/upscale/dir',
        json={'input_dir': '../../../Windows/System32'},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body is not None
    assert 'error' in body
    assert 'traversal' in body['error'].lower() or 'denied' in body['error'].lower()


def test_dir_no_input_dir(client):
    """Directory mode with missing input_dir field returns 400."""
    resp = client.post('/api/upscale/dir', json={})
    assert resp.status_code == 400
    body = resp.get_json()
    assert body is not None
    assert 'error' in body


# ═══════════════════════════════════════════════════════════════════════
# GET /api/status/<task_id>
# ═══════════════════════════════════════════════════════════════════════


def test_status_not_found(client):
    """Querying a non-existent task returns 404."""
    resp = client.get('/api/status/nonexistent')
    assert resp.status_code == 404
    body = resp.get_json()
    assert body is not None
    assert 'error' in body
