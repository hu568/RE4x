"""Tests for :mod:`core` — the Flask-free upscale service behind the GUI.

Mixed-speed suite: param parsing and validation are instant; a few
pipeline tests exercise the real engine + ffmpeg binaries (as before,
no mocking anywhere).
"""

import os
import time

from PIL import Image

# ── Param parsing (fast, no binaries) ────────────────────────────────────


def test_parse_params_defaults(service):
    parsed, err = service.parse_params({})
    assert err is None
    assert parsed['model'] == 'realesrgan-x4plus-anime'
    assert parsed['target_scale'] == 2.0
    assert parsed['model_2'] is None
    assert parsed['mix_ratio'] == 0.5
    assert parsed['output_format'] == 'png'


def test_parse_params_scale(service):
    parsed, err = service.parse_params({'scale': '4'})
    assert err is None
    assert parsed['target_scale'] == 4.0


def test_parse_params_dimension(service):
    parsed, err = service.parse_params({'width': 800, 'height': 600, 'crop': True})
    assert err is None
    assert parsed['final_w'] == 800
    assert parsed['final_h'] == 600
    assert parsed['crop'] is True


def test_parse_params_invalid_scale(service):
    _, err = service.parse_params({'scale': '0'})
    assert err is not None
    _, err = service.parse_params({'scale': '99'})
    assert err is not None


def test_parse_params_nan_scale(service):
    _, err = service.parse_params({'scale': 'nan'})
    assert err is not None


def test_parse_params_invalid_mix_ratio(service):
    _, err = service.parse_params({'mix_ratio': '1.5'})
    assert err is not None


def test_parse_params_bad_model(service):
    _, err = service.parse_params({'model': 'this-model-does-not-exist'})
    assert err is not None
    assert 'Unknown model' in err


def test_parse_params_video_formats(service):
    """Video tasks must accept mp4/avi/gif — and NOT rewrite mp4 to png.

    Regression test: parse_params used to force any non-(png/jpg) value to
    'png', so video tasks reported the absurd 'Unsupported output format: png'.
    """
    from core import VIDEO_OUTPUT_FORMATS  # noqa: PLC0415

    for fmt in VIDEO_OUTPUT_FORMATS:
        parsed, err = service.parse_params(
            {'output_format': fmt}, output_formats=VIDEO_OUTPUT_FORMATS)
        assert err is None, f'{fmt} should be accepted: {err}'
        assert parsed['output_format'] == fmt

    # Default (no output_format) → first allowed format (mp4 for video)
    parsed, err = service.parse_params(
        {}, output_formats=VIDEO_OUTPUT_FORMATS)
    assert err is None
    assert parsed['output_format'] == 'mp4'

    # Still rejects truly unsupported formats
    _, err = service.parse_params(
        {'output_format': 'png'}, output_formats=VIDEO_OUTPUT_FORMATS)
    assert err is not None
    assert 'Unsupported output format' in err


def test_parse_params_model2_none_sentinel(service):
    parsed, err = service.parse_params({'model_2': 'None'})
    assert err is None
    assert parsed['model_2'] is None


def test_parse_params_bad_dimensions(service):
    _, err = service.parse_params({'width': 'abc', 'height': 100})
    assert err is not None
    _, err = service.parse_params({'width': 0, 'height': 100})
    assert err is not None


# ── Models ───────────────────────────────────────────────────────────────


def test_service_get_models(service):
    models = service.get_models()
    names = [m['name'] for m in models]
    assert 'realesrgan-x4plus' in names
    assert 'realesrgan-x4plus-anime' in names


# ── Task helpers ─────────────────────────────────────────────────────────


def _wait_done(service, task_id, timeout=180):
    """Block until the task finishes; return its final state."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        t = service.get_task(task_id)
        if t and t['status'] in ('done', 'error'):
            return t
        time.sleep(0.3)
    raise TimeoutError(f'Task {task_id} did not finish within {timeout}s')


# ── Single image ─────────────────────────────────────────────────────────


def test_submit_single_missing_file(service):
    tid = service.submit_single('/nonexistent/input.jpg', {})
    t = _wait_done(service, tid, timeout=30)
    assert t['status'] == 'error'
    assert t['error']


def test_submit_single_bad_extension(service, tmp_dir):
    txt = os.path.join(tmp_dir, 'not_an_image.txt')
    with open(txt, 'w', encoding='utf-8') as f:
        f.write('hello')
    tid = service.submit_single(txt, {})
    t = _wait_done(service, tid, timeout=30)
    assert t['status'] == 'error'
    assert t['error']


def test_submit_single_pipeline(service, test_img):
    """Full two-step pipeline: model 4x → ffmpeg scale to 2x (220→440)."""
    tid = service.submit_single(test_img, {'scale': 2})
    t = _wait_done(service, tid)
    assert t['status'] == 'done', t.get('error')
    assert len(t['results']) == 1
    out = t['results'][0]['path']
    assert os.path.isfile(out)
    with Image.open(out) as img:
        assert img.size == (440, 440)


def test_submit_single_dimension_crop(service, test_img):
    """Dimension mode with crop: 220×220 → exact 600×400."""
    tid = service.submit_single(
        test_img, {'width': 600, 'height': 400, 'crop': True})
    t = _wait_done(service, tid)
    assert t['status'] == 'done', t.get('error')
    assert len(t['results']) == 1
    with Image.open(t['results'][0]['path']) as img:
        assert img.size == (600, 400)


def test_submit_single_dimension_fit(service, test_img):
    """Dimension mode, fit (contain): 220×220 stays square inside 600×400."""
    tid = service.submit_single(
        test_img, {'width': 600, 'height': 400, 'crop': False})
    t = _wait_done(service, tid)
    assert t['status'] == 'done', t.get('error')
    assert len(t['results']) == 1
    with Image.open(t['results'][0]['path']) as img:
        assert img.size == (400, 400)


# ── Batch / directory ────────────────────────────────────────────────────


def test_submit_files(service, test_img, test_img2):
    tid = service.submit_files([test_img, test_img2], {'scale': 2})
    t = _wait_done(service, tid)
    assert t['status'] == 'done', t.get('error')
    assert len(t['results']) == 2
    for r in t['results']:
        assert os.path.isfile(r['path'])


def test_submit_dir_missing(service):
    tid = service.submit_dir('/nonexistent/dir', None, {'scale': 2})
    t = _wait_done(service, tid, timeout=30)
    assert t['status'] == 'error'


def test_submit_dir(service, test_img, test_img2, tmp_dir):
    import shutil
    in_dir = os.path.join(tmp_dir, 'core_dir_in')
    out_dir = os.path.join(tmp_dir, 'core_dir_out')
    os.makedirs(in_dir, exist_ok=True)
    shutil.copy2(test_img, os.path.join(in_dir, 'a.jpg'))
    shutil.copy2(test_img2, os.path.join(in_dir, 'b.png'))

    tid = service.submit_dir(in_dir, out_dir, {'scale': 2})
    t = _wait_done(service, tid)
    assert t['status'] == 'done', t.get('error')
    assert len(t['results']) == 2
    for r in t['results']:
        assert os.path.isfile(r['path'])
        assert os.path.dirname(os.path.realpath(r['path'])) == os.path.realpath(out_dir)


# ── Video ────────────────────────────────────────────────────────────────


def test_submit_video_missing(service):
    tid = service.submit_video('/nonexistent/video.mp4', {'scale': 2})
    t = _wait_done(service, tid, timeout=30)
    assert t['status'] == 'error'


def test_submit_video_bad_extension(service, tmp_dir):
    txt = os.path.join(tmp_dir, 'fake_video.txt')
    with open(txt, 'w', encoding='utf-8') as f:
        f.write('not a video')
    tid = service.submit_video(txt, {'scale': 2})
    t = _wait_done(service, tid, timeout=30)
    assert t['status'] == 'error'


def test_submit_video_bad_output_format(service, test_img):
    tid = service.submit_video(test_img, {'output_format': 'mkv'})
    t = _wait_done(service, tid, timeout=30)
    assert t['status'] == 'error'


def test_submit_video_mp4_end_to_end(service, project_root):
    """Real end-to-end video upscale: extract → model 4x → resize → merge.

    Regression test for two v2.0 bugs:
      1. parse_params rewrote 'mp4' → 'png' (wrong format whitelist)
      2. ffmpeg 9.0 removed -vsync (now -fps_mode cfr) → extraction failed
    """
    video = os.path.join(project_root, 'test-data', 'onepiece_demo.mp4')
    if not os.path.isfile(video):
        pytest.skip('test-data/onepiece_demo.mp4 missing')

    tid = service.submit_video(
        video, {'scale': 2, 'output_format': 'mp4'})
    t = _wait_done(service, tid, timeout=420)
    assert t['status'] == 'done', t.get('error')
    assert len(t['results']) == 1
    assert t['results'][0]['filename'].endswith('.mp4')
    assert os.path.isfile(t['results'][0]['path'])


def test_submit_video_dimension_crop(service, project_root, tmp_dir):
    """Video dimension mode with crop: 640x480 source → exact 320x180.

    Regression test: dimension mode was ignored by video tasks (fell back
    to 2x scale). Cover path scales the 4x frame to fill the target box
    then center-crops to the exact requested size.
    """
    video = os.path.join(project_root, 'test-data', 'onepiece_demo.mp4')
    if not os.path.isfile(video):
        pytest.skip('test-data/onepiece_demo.mp4 missing')

    from subprocess import run as subprocess_run  # noqa: PLC0415

    tid = service.submit_video(
        video, {'width': 320, 'height': 180, 'crop': True,
                'output_format': 'mp4'})
    t = _wait_done(service, tid, timeout=420)
    assert t['status'] == 'done', t.get('error')
    assert len(t['results']) == 1

    out = t['results'][0]['path']
    frame = os.path.join(tmp_dir, 'verify_dim_crop.jpg')
    subprocess_run(
        [service.resizer._ffmpeg_path, '-y', '-i', out,
         '-frames:v', '1', frame],
        capture_output=True)
    with Image.open(frame) as img:
        assert img.size == (320, 180), f'crop mode should be 320x180, got {img.size}'


# ── Zip results ──────────────────────────────────────────────────────────


def test_zip_results_invalid_task_id(service, tmp_dir):
    dest = os.path.join(tmp_dir, 'bad.zip')
    r = service.zip_results('../../etc/passwd', dest)
    assert not r['success']


def test_zip_results_unknown_task(service, tmp_dir):
    dest = os.path.join(tmp_dir, 'unknown.zip')
    r = service.zip_results('deadbeef', dest)
    assert not r['success']


# ── Dimension-mode even sizing (issue #1) ───────────────────────────────
# Regression: contain/crop dimension mode could compute ODD dimensions
# (e.g. round(960×2.2222)=2133), which libx264 + yuv420p reject with
# "width not divisible by 2" during the video frame merge.


def test_even_dimension():
    """_even_dimension rounds down to the nearest even number (min 2)."""
    from core import _even_dimension  # noqa: PLC0415

    assert _even_dimension(2133) == 2132
    assert _even_dimension(7) == 6
    assert _even_dimension(2) == 2
    assert _even_dimension(1) == 2   # never 0
    assert _even_dimension(0) == 2   # never 0


def test_ffmpeg_error_keeps_tail():
    """Error text keeps the TAIL of stderr (the real error, not the banner)."""
    from core import _ffmpeg_error  # noqa: PLC0415

    banner = b'ffmpeg version 9.0 ' + b'x' * 600 + b'\n'
    err = _ffmpeg_error(banner +
                        b'width not divisible by 2 (2133x3840)\n'
                        b'Error while opening encoder\nConversion failed!\n')
    assert 'width not divisible by 2' in err
    assert 'Conversion failed!' in err
    assert len(err) <= 500


def test_ffmpeg_error_short_untouched():
    """Short stderr is returned in full (no truncation)."""
    from core import _ffmpeg_error  # noqa: PLC0415

    assert _ffmpeg_error(b'  short error  ') == 'short error'


def test_compute_dimension_upscale_contain_odd(project_root, tmp_dir):
    """Issue #1: contain with odd rounding → even output.

    960×1728 source into 2160×3840: scale 2.2222 → round(960×2.2222) = 2133
    (odd) → now rounded down to 2132.
    """
    from core import _compute_dimension_upscale  # noqa: PLC0415

    src = os.path.join(tmp_dir, 'dim_src_960x1728.png')
    Image.new('RGB', (960, 1728), (128, 128, 128)).save(src)
    w, h, _ = _compute_dimension_upscale(src, 2160, 3840, crop=False)
    assert w == 2132 and h == 3840
    assert w % 2 == 0 and h % 2 == 0


def test_compute_dimension_upscale_crop_odd(project_root, tmp_dir):
    """Issue #1: odd crop targets are rounded down to even."""
    from core import _compute_dimension_upscale  # noqa: PLC0415

    src = os.path.join(tmp_dir, 'dim_src_crop.png')
    Image.new('RGB', (100, 100), (0, 0, 0)).save(src)
    w, h, _ = _compute_dimension_upscale(src, 2161, 3841, crop=True)
    assert w == 2160 and h == 3840


def test_submit_single_dimension_contain_odd(service, tmp_dir):
    """Issue #1 (single image): contain on odd rounding → even output."""
    src = os.path.join(tmp_dir, 'single_contain_640x480.png')
    Image.new('RGB', (640, 480), (64, 128, 192)).save(src)
    tid = service.submit_single(
        src, {'width': 1000, 'height': 700, 'crop': False})
    t = _wait_done(service, tid, timeout=180)
    assert t['status'] == 'done', t.get('error')
    with Image.open(t['results'][0]['path']) as img:
        assert img.size == (932, 700), img.size
        assert img.size[0] % 2 == 0 and img.size[1] % 2 == 0


def test_submit_single_dimension_crop_odd(service, test_img):
    """Issue #1 (single image): odd crop target → even output."""
    tid = service.submit_single(
        test_img, {'width': 601, 'height': 401, 'crop': True})
    t = _wait_done(service, tid, timeout=180)
    assert t['status'] == 'done', t.get('error')
    with Image.open(t['results'][0]['path']) as img:
        assert img.size == (600, 400), img.size


def test_submit_video_dimension_contain_odd(service, project_root, tmp_dir):
    """Issue #1 (video): contain on odd rounding → even output.

    640×480 source into 1000×700: the h-ratio binds (1.4583) →
    round(640×1.4583) = 933 (odd) previously broke the libx264/yuv420p
    merge with "width not divisible by 2"; the frame is now 932×700.
    """
    video = os.path.join(project_root, 'test-data', 'onepiece_demo.mp4')
    if not os.path.isfile(video):
        pytest.skip('test-data/onepiece_demo.mp4 missing')

    tid = service.submit_video(
        video, {'width': 1000, 'height': 700, 'crop': False,
                'output_format': 'mp4'})
    t = _wait_done(service, tid, timeout=420)
    assert t['status'] == 'done', t.get('error')
    assert len(t['results']) == 1

    out = t['results'][0]['path']
    frame = os.path.join(tmp_dir, 'verify_dim_contain.jpg')
    from subprocess import run as subprocess_run  # noqa: PLC0415
    subprocess_run(
        [service.resizer._ffmpeg_path, '-y', '-i', out,
         '-frames:v', '1', frame],
        capture_output=True)
    with Image.open(frame) as img:
        assert img.size == (932, 700), \
            f'contain should be 932x700, got {img.size}'
        assert img.size[0] % 2 == 0 and img.size[1] % 2 == 0


def test_submit_video_dimension_crop_odd(service, project_root, tmp_dir):
    """Issue #1 (video): odd crop target → even output (961x721 → 960x720).

    Cover path: 4x frame → resize to fill box (mid) → center-crop to the
    even-adjusted final size, so the encoded frames stay even.
    """
    video = os.path.join(project_root, 'test-data', 'onepiece_demo.mp4')
    if not os.path.isfile(video):
        pytest.skip('test-data/onepiece_demo.mp4 missing')

    tid = service.submit_video(
        video, {'width': 961, 'height': 721, 'crop': True,
                'output_format': 'mp4'})
    t = _wait_done(service, tid, timeout=420)
    assert t['status'] == 'done', t.get('error')
    assert len(t['results']) == 1

    out = t['results'][0]['path']
    frame = os.path.join(tmp_dir, 'verify_dim_crop_odd.jpg')
    from subprocess import run as subprocess_run  # noqa: PLC0415
    subprocess_run(
        [service.resizer._ffmpeg_path, '-y', '-i', out,
         '-frames:v', '1', frame],
        capture_output=True)
    with Image.open(frame) as img:
        assert img.size == (960, 720), \
            f'crop should be 960x720, got {img.size}'
        assert img.size[0] % 2 == 0 and img.size[1] % 2 == 0
