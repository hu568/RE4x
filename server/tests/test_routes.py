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
# Parameter validation (scale / mix_ratio)
# ═══════════════════════════════════════════════════════════════════════


def test_upscale_invalid_scale(client, make_image):
    """Non-numeric scale returns 400 instead of crashing with a 500."""
    data = {
        'file': (make_image(), 'test.jpg'),
        'scale': 'not-a-number',
    }
    resp = client.post('/api/upscale', data=data, content_type='multipart/form-data')
    assert resp.status_code == 400
    assert 'scale' in resp.get_json()['error']


def test_upscale_scale_out_of_range(client, make_image):
    """Scale outside 0.1–8.0 is rejected with 400."""
    for bad in ('0', '0.05', '99', '-2'):
        data = {
            'file': (make_image(), 'test.jpg'),
            'scale': bad,
        }
        resp = client.post('/api/upscale', data=data, content_type='multipart/form-data')
        assert resp.status_code == 400, f'scale={bad} should be rejected, got {resp.status_code}'
        assert 'scale' in resp.get_json()['error']


def test_upscale_invalid_mix_ratio(client, make_image):
    """mix_ratio outside 0–1 returns 400."""
    data = {
        'file': (make_image(), 'test.jpg'),
        'scale': '2',
        'mix_ratio': '1.5',
    }
    resp = client.post('/api/upscale', data=data, content_type='multipart/form-data')
    assert resp.status_code == 400
    assert 'mix_ratio' in resp.get_json()['error']


def test_upscale_nan_scale(client, make_image):
    """NaN scale must be rejected, not silently pass range checks."""
    data = {
        'file': (make_image(), 'test.jpg'),
        'scale': 'nan',
    }
    resp = client.post('/api/upscale', data=data, content_type='multipart/form-data')
    assert resp.status_code == 400
    assert 'scale' in resp.get_json()['error']


def test_batch_invalid_scale(client, make_image):
    """Batch with a non-numeric scale returns 400."""
    data = {
        'files': (make_image(), 'img1.jpg'),
        'scale': 'abc',
    }
    resp = client.post('/api/upscale/batch', data=data, content_type='multipart/form-data')
    assert resp.status_code == 400
    assert 'scale' in resp.get_json()['error']


def test_dir_invalid_scale(client):
    """Directory mode with a non-numeric scale returns 400."""
    resp = client.post('/api/upscale/dir', json={'input_dir': '.', 'scale': 'abc'})
    assert resp.status_code == 400
    assert 'scale' in resp.get_json()['error']


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
    """Directory mode: ``..`` is resolved harmlessly; non-existent path returns 400."""
    resp = client.post(
        '/api/upscale/dir',
        json={'input_dir': '../../../Windows/System32'},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body is not None
    assert 'error' in body
    # Error should be about path not being found (resolved safely),
    # not about traversal denial
    assert 'not found' in body['error'].lower() or 'not readable' in body['error'].lower()


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


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/results/<task_id>/...  — path-traversal protection
# ═══════════════════════════════════════════════════════════════════════════


def test_results_bad_task_id_format(client):
    """Malformed task ids (non-8-hex) are rejected outright — never joined
    into a filesystem path."""
    # Encoded traversal payloads previously reached os.path.join via the
    # <task_id> route variable (URL-decoded backslashes/slashes).
    # Note: some payloads (encoded '/') are rejected by Werkzeug's router
    # itself with a plain-HTML 404 — both rejection styles are acceptable.
    for url in (
        '/api/results/..%5C..%5C..%5Ctest-data/download',
        '/api/results/..%2F..%2Ftest-data/download',
        '/api/results/..%5C..%5Ctest-data/input.jpg',
        '/api/results/abc/input.jpg',           # not hex
        '/api/results/ABCDEFGH/input.jpg',      # uppercase hex rejected
        '/api/results/abcdefgh!/input.jpg',     # stray char
    ):
        resp = client.get(url)
        assert resp.status_code == 404, f'{url} should be 404, got {resp.status_code}'
        body = resp.get_json(silent=True)
        if body is not None:
            assert 'error' in body


def test_results_serve_denies_filename_traversal(client, project_root):
    """A valid task id combined with a traversing filename is denied."""
    resp = client.get('/api/results/aaaaaaaa/..%5C..%5C..%5C..%5Ctest-data%5Cinput.jpg')
    assert resp.status_code in (403, 404)  # 403 traversal / 404 not found
    resp = client.get('/api/results/aaaaaaaa/..%2F..%2F..%2F..%2Ftest-data%2Finput.jpg')
    assert resp.status_code in (403, 404)


def test_results_download_unknown_task(client):
    """Well-formed but unknown task id yields 404 (not a filesystem error)."""
    resp = client.get('/api/results/aaaaaaaa/download')
    assert resp.status_code == 404
    assert 'error' in resp.get_json()


# ═══════════════════════════════════════════════════════════════════════════
# Unified pipeline: model 4x → ffmpeg resize
# ═══════════════════════════════════════════════════════════════════════════


def test_upscale_scale_6x(client, make_image):
    """Scale 6x: model upscales 4x, then ffmpeg resizes to 6x.

    Input 100×100 → model outputs 400×400 → ffmpeg ×1.5 → 600×600.
    """
    data = {
        'file': (make_image((100, 100)), 'test.jpg'),
        'scale': '6',
        'model': 'realesr-animevideov3',
    }
    resp = client.post('/api/upscale', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200, \
        f'Expected 200, got {resp.status_code}: {resp.get_json(silent=True)}'
    assert resp.content_type.startswith('image/')

    from PIL import Image
    import io
    img = Image.open(io.BytesIO(resp.data))
    assert img.size == (600, 600), f"Expected 600x600, got {img.size}"


def test_upscale_scale_2x(client, make_image):
    """Scale 2x: model 4x → ffmpeg ×0.5 → 2x final.

    Input 100×100 → model 400×400 → ffmpeg ×0.5 → 200×200.
    """
    data = {
        'file': (make_image((100, 100)), 'test.jpg'),
        'scale': '2',
        'model': 'realesr-animevideov3',
    }
    resp = client.post('/api/upscale', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200, \
        f'Expected 200, got {resp.status_code}: {resp.get_json(silent=True)}'

    from PIL import Image
    import io
    img = Image.open(io.BytesIO(resp.data))
    assert img.size == (200, 200), f"Expected 200x200, got {img.size}"


def test_upscale_scale_4x(client, make_image):
    """Scale 4x: model 4x → ffmpeg ×1.0 (effectively a re-encode).

    Input 100×100 → output 400×400.
    """
    data = {
        'file': (make_image((100, 100)), 'test.jpg'),
        'scale': '4',
        'model': 'realesr-animevideov3',
    }
    resp = client.post('/api/upscale', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200, \
        f'Expected 200, got {resp.status_code}: {resp.get_json(silent=True)}'

    from PIL import Image
    import io
    img = Image.open(io.BytesIO(resp.data))
    assert img.size == (400, 400), f"Expected 400x400, got {img.size}"


# ═══════════════════════════════════════════════════════════════════════════
# Dimension mode
# ═══════════════════════════════════════════════════════════════════════════


def test_upscale_dimension_mode(client, make_image):
    """Dimension mode: target 800×600, input 100×100.

    Without crop (contain): effective_scale = min(8, 6) = 6.
    Model 4x → ffmpeg ×1.5 → 600×600 (fits within 800×600).
    """
    data = {
        'file': (make_image((100, 100)), 'test.jpg'),
        'width': '800',
        'height': '600',
        'model': 'realesr-animevideov3',
    }
    resp = client.post('/api/upscale', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200, \
        f'Expected 200, got {resp.status_code}: {resp.get_json(silent=True)}'

    from PIL import Image
    import io
    img = Image.open(io.BytesIO(resp.data))
    # contain: output fits within 800×600, aspect ratio preserved
    # 100×100, scale=min(8,6)=6 → 600×600
    assert img.size == (600, 600), f"Expected 600x600 (contain), got {img.size}"


def test_upscale_dimension_crop(client, make_image):
    """Dimension mode with crop: target 400×400 from 100×200 input.

    With crop (cover): effective_scale = max(4, 2) = 4.
    Model 4x → 400×800 → ffmpeg crop center to 400×400.
    """
    data = {
        'file': (make_image((100, 200)), 'test.jpg'),
        'width': '400',
        'height': '400',
        'crop': 'true',
        'model': 'realesr-animevideov3',
    }
    resp = client.post('/api/upscale', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200, \
        f'Expected 200, got {resp.status_code}: {resp.get_json(silent=True)}'

    from PIL import Image
    import io
    img = Image.open(io.BytesIO(resp.data))
    assert img.size == (400, 400), f"Expected 400x400 (crop), got {img.size}"


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/upscale/video
# ═══════════════════════════════════════════════════════════════════════════


def test_video_no_file(client):
    """Video endpoint with no file returns 400."""
    resp = client.post('/api/upscale/video', content_type='multipart/form-data')
    assert resp.status_code == 400
    body = resp.get_json()
    assert body is not None
    assert 'error' in body


def test_video_bad_extension(client):
    """Video endpoint with non-video extension returns 400."""
    data = {'file': (io.BytesIO(b'not a video'), 'test.txt')}
    resp = client.post('/api/upscale/video', data=data, content_type='multipart/form-data')
    assert resp.status_code == 400
    body = resp.get_json()
    assert body is not None
    assert 'error' in body
