"""Core upscaling service — Flask-free logic for the SD Enhance desktop GUI.

Extracted from the old ``routes.py`` (Web API). Everything here is plain
Python: an ``UpscaleService`` owns the engine/mixer/resizer instances, a
``TaskManager`` tracks async jobs, and the GUI bridge (``gui_api.py``)
exposes these to the pywebview frontend.

All long-running work runs in daemon threads behind a ``task_id``; the
frontend polls :meth:`UpscaleService.get_task` for progress/results.
"""

import logging
import math
import os
import re
import shutil
import threading
import uuid
import zipfile

from PIL import Image

from procutils import popen

logger = logging.getLogger('sd_enhance.core')

# ── Constants ─────────────────────────────────────────────────────────────

# GUI 显示版本号（打包 release 时与 package_release.py 的版本一致）
APP_VERSION = '2.1.2'

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff'}
VIDEO_EXTENSIONS = {'.mp4', '.webm', '.avi', '.mov', '.mkv'}
VIDEO_OUTPUT_FORMATS = ('mp4', 'avi', 'gif')

DEFAULT_MODEL = 'realesrgan-x4plus-anime'

# Task IDs are 8-char lowercase hex prefixes of UUID4 (see TaskManager.create_task).
_VALID_TASK_ID_RE = re.compile(r'^[0-9a-f]{8}$')


# ── Task Manager ──────────────────────────────────────────────────────────

class TaskManager:
    """In-memory task manager with background thread execution.

    Stores task state in a dict keyed by 8-character task ID.
    Each entry: {status, progress, results, error}
    """

    def __init__(self, max_tasks: int = 100):
        self._tasks: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._max_tasks = max_tasks
        self._order: list[str] = []  # insertion order for eviction

    # ── CRUD ───────────────────────────────────────────────────────────────

    def create_task(self) -> str:
        task_id = str(uuid.uuid4())[:8]
        with self._lock:
            self._tasks[task_id] = {
                'status': 'queued',
                'progress': 0,
                'results': [],
                'error': None,
            }
            self._order.append(task_id)
            self._last_evicted = self._evict_locked()
        return task_id

    def _evict_locked(self) -> list[str]:
        """Drop the oldest finished tasks beyond ``_max_tasks``.

        Returns the evicted task ids (caller may clean their result dirs).
        Only finished tasks are evicted; queued/processing ones are kept.
        """
        evicted: list[str] = []
        while len(self._tasks) > self._max_tasks:
            for tid in self._order:
                task = self._tasks.get(tid)
                if task and task.get('status') in ('done', 'error'):
                    self._tasks.pop(tid, None)
                    self._order.remove(tid)
                    evicted.append(tid)
                    break
            else:
                break  # only unfinished tasks remain
        return evicted

    def update_task(self, task_id: str, **kwargs) -> None:
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].update(kwargs)

    def get_task(self, task_id: str) -> dict | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return dict(task) if task else None

    def remove_task(self, task_id: str) -> None:
        with self._lock:
            self._tasks.pop(task_id, None)

    # ── Background execution ──────────────────────────────────────────────

    def run_task(self, task_id: str, func, *args, **kwargs) -> None:
        """Run *func* in a daemon background thread.

        The function receives the same keyword arguments passed here plus
        ``task_manager`` and ``task_id``. Before calling, status is set to
        ``processing``; after success → ``done`` with result list; on
        exception → ``error`` with message.
        """

        def _run():
            try:
                self.update_task(task_id, status='processing')
                results = func(*args, **kwargs,
                               task_manager=self, task_id=task_id)
                # If the task body already flagged an error, keep it.
                with self._lock:
                    task = self._tasks.get(task_id)
                if task and task.get('status') == 'error':
                    logger.error('[%s] task failed: %s',
                                 task_id, task.get('error'))
                    return
                self.update_task(task_id, status='done',
                                 results=results, progress=100)
                logger.info('[%s] task done: %d result(s)',
                            task_id, len(results or []))
            except Exception as e:
                logger.exception('[%s] task crashed: %s', task_id, e)
                self.update_task(task_id, status='error', error=str(e))

        t = threading.Thread(target=_run, daemon=True)
        t.start()


# ── Helpers ───────────────────────────────────────────────────────────────

def _get_base_path() -> str:
    """Return the project root directory.

    - Frozen exe sits at the project root (next to ``tools/``).
    - Development: current working directory.
    """
    import sys
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.realpath(sys.executable))
    return os.getcwd()


def _is_image_file(filename: str) -> bool:
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXTENSIONS


def _is_video_file(filename: str) -> bool:
    _, ext = os.path.splitext(filename.lower())
    return ext in VIDEO_EXTENSIONS


def _parse_float(
    value,
    default: float,
    *,
    min_val: float | None = None,
    max_val: float | None = None,
) -> tuple[float, str | None]:
    """Parse *value* as a float, falling back to *default* on empty input.

    Returns ``(parsed, None)`` on success or ``(default, error_message)``
    when *value* is not a number or falls outside [min_val, max_val].
    """
    if value is None or value == '':
        return default, None
    if isinstance(value, bool):
        return default, f'Invalid number: {value!r}'
    try:
        v = float(value)
    except (ValueError, TypeError):
        return default, f'Invalid number: {value!r}'
    if not math.isfinite(v):
        return default, f'Value must be a finite number, got: {value!r}'
    if min_val is not None and v < min_val:
        return default, f'Value must be >= {min_val}'
    if max_val is not None and v > max_val:
        return default, f'Value must be <= {max_val}'
    return v, None


def _cleanup_files(*paths: str | None) -> None:
    """Remove temporary files, silently ignoring errors."""
    for p in paths:
        if p and os.path.isfile(p):
            try:
                os.remove(p)
            except Exception:
                pass


def _run_upscale_pipeline(
    input_path: str,
    output_path: str,
    model: str,
    target_scale: float,
    engine,
    resizer,
    tmp_dir: str,
) -> dict:
    """Unified two-step upscale pipeline.

    Always: model upscale at 4x → ffmpeg resize to *target_scale*.
    """
    tmp_4x = os.path.join(tmp_dir, f"pipe4x_{uuid.uuid4().hex}.png")
    r = engine.upscale(input_path, tmp_4x, model=model, scale=4)
    if not r['success']:
        _cleanup_files(tmp_4x)
        return {"success": False, "output_path": output_path,
                "error": f"Model upscale failed: {r['error']}"}

    ffmpeg_scale = target_scale / 4.0
    result = resizer.resize_by_scale(tmp_4x, output_path, scale=ffmpeg_scale)
    _cleanup_files(tmp_4x)
    return result


def _compute_dimension_upscale(
    input_path: str,
    target_w: int,
    target_h: int,
    crop: bool,
) -> tuple[int, int, float]:
    """Compute output dimensions and effective scale for dimension mode.

    Returns ``(final_w, final_h, effective_scale)``. ``crop=True`` → cover
    (fill target box, crop overflow); ``crop=False`` → contain (fit inside).
    """
    with Image.open(input_path) as img:
        src_w, src_h = img.size

    w_ratio = target_w / src_w
    h_ratio = target_h / src_h

    if crop:
        effective_scale = max(w_ratio, h_ratio)
        final_w, final_h = target_w, target_h
    else:
        effective_scale = min(w_ratio, h_ratio)
        final_w = max(1, round(src_w * effective_scale))
        final_h = max(1, round(src_h * effective_scale))

    return final_w, final_h, effective_scale


def _detect_fps(ffmpeg_dir: str, video_path: str) -> float:
    """Detect frame-rate of *video_path* using ffprobe or ffmpeg.

    Prefers ``avg_frame_rate`` over ``r_frame_rate``; falls back to 24.0.
    """
    import json as _json
    from subprocess import PIPE

    ffprobe_path = os.path.join(ffmpeg_dir, 'ffprobe.exe')
    if not os.path.isfile(ffprobe_path):
        ffprobe_path = os.path.join(ffmpeg_dir, 'ffprobe')

    if os.path.isfile(ffprobe_path):
        args = [
            ffprobe_path,
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_streams',
            video_path,
        ]
        try:
            proc = popen(args, stdout=PIPE, stderr=PIPE, shell=False)
            stdout, _ = proc.communicate(timeout=30)
            if proc.returncode == 0 and stdout:
                info = _json.loads(stdout)
                for stream in info.get('streams', []):
                    if stream.get('codec_type') == 'video':
                        for key in ('avg_frame_rate', 'r_frame_rate'):
                            fps_str = stream.get(key, '')
                            if fps_str and '/' in fps_str:
                                num, den = fps_str.split('/')
                                if int(den) != 0:
                                    fps = float(num) / float(den)
                                    if fps > 0:
                                        return round(fps, 2)
        except Exception:
            pass

    # Fallback: parse ffmpeg -i output
    ffmpeg_path = os.path.join(ffmpeg_dir, 'ffmpeg.exe')
    args = [ffmpeg_path, '-i', video_path]
    try:
        proc = popen(args, stdout=PIPE, stderr=PIPE, shell=False)
        _, stderr = proc.communicate(timeout=30)
        output = stderr.decode('utf-8', errors='replace')
        match = re.search(r'Video:.*?(\d+\.?\d*)\s*fps', output)
        if match:
            fps = float(match.group(1))
            if fps > 0:
                return fps
        match = re.search(r'Video:.*?(\d+\.?\d*)\s*tbr', output)
        if match:
            fps = float(match.group(1))
            if fps > 0:
                return fps
    except Exception:
        pass

    return 24.0


# ── Upscale Service ───────────────────────────────────────────────────────

class UpscaleService:
    """High-level service backing the GUI: owns engine/mixer/resizer and
    exposes synchronous (single) and asynchronous (batch/dir/video) tasks.
    """

    def __init__(self, engine, mixer, resizer, models_dir: str,
                 base_path: str | None = None):
        self.engine = engine
        self.mixer = mixer
        self.resizer = resizer
        self.models_dir = models_dir
        self.base_path = base_path or _get_base_path()
        self.tmp_dir = os.path.join(self.base_path, 'TMP')
        self.tasks = TaskManager()

        os.makedirs(self.tmp_dir, exist_ok=True)

    # ── Models ────────────────────────────────────────────────────────────

    def get_models(self) -> list[dict]:
        from models import get_available_models  # noqa: PLC0415
        return get_available_models(self.models_dir)

    # ── Param parsing ─────────────────────────────────────────────────────

    def parse_params(self, params: dict | None,
                     output_formats: tuple = ('png', 'jpg')) -> tuple[dict, str | None]:
        """Validate/normalise GUI parameters.

        Args:
            params: Raw GUI parameter dict.
            output_formats: Allowed output formats for this task type.
                Image tasks default to ``('png', 'jpg')``; video tasks pass
                ``VIDEO_OUTPUT_FORMATS`` (mp4/avi/gif). The value is never
                silently rewritten — an unsupported format raises an error.

        Returns ``(params, None)`` on success or ``(None, error_msg)``.
        Normalised keys: model, model_2, mix_ratio, target_scale,
        final_w, final_h, crop, output_format.
        """
        params = params or {}

        model = params.get('model') or DEFAULT_MODEL
        model_2 = params.get('model_2')
        if model_2 in (None, '', 'None'):
            model_2 = None

        # Validate model names against what's actually installed
        available = {m['name'] for m in self.get_models()}
        if model not in available:
            return None, f'Unknown model: {model} (installed: {", ".join(sorted(available)) or "none"})'
        if model_2 and model_2 not in available:
            return None, f'Unknown model: {model_2}'

        mix_ratio, err = _parse_float(
            params.get('mix_ratio'), 0.5, min_val=0.0, max_val=1.0,
        )
        if err:
            return None, f'mix_ratio: {err}'

        crop = params.get('crop') in (True, 'true', '1', 'yes')

        output_format = str(
            params.get('output_format') or output_formats[0]).lower().strip()
        if output_format not in output_formats:
            return None, (
                f'Unsupported output format: {output_format} '
                f'(allowed: {", ".join(output_formats)})'
            )

        # Scale vs dimension mode
        target_scale: float | None = None
        final_w = final_h = None

        width_str = params.get('width')
        height_str = params.get('height')
        has_dim = (width_str not in (None, '')) and (height_str not in (None, ''))
        if has_dim:
            try:
                final_w = int(width_str)
                final_h = int(height_str)
            except (ValueError, TypeError):
                return None, 'Invalid width/height values'
            if final_w < 1 or final_h < 1:
                return None, 'Width and height must be positive'
        elif params.get('scale'):
            target_scale, err = _parse_float(
                params.get('scale'), None, min_val=0.1, max_val=8.0,
            )
            if err:
                return None, f'scale: {err}'
        else:
            target_scale = 2.0

        return {
            'model': model,
            'model_2': model_2,
            'mix_ratio': mix_ratio,
            'crop': crop,
            'target_scale': target_scale,
            'final_w': final_w,
            'final_h': final_h,
            'output_format': output_format,
        }, None
    # ── Task plumbing ─────────────────────────────────────────────────────

    def create_task(self) -> str:
        task_id = self.tasks.create_task()
        # Clean up result dirs of evicted tasks (keep TMP/ tidy)
        evicted = getattr(self.tasks, '_last_evicted', [])
        for tid in evicted:
            shutil.rmtree(
                os.path.join(self.tmp_dir, 'results', tid),
                ignore_errors=True,
            )
        return task_id

    def get_task(self, task_id: str) -> dict | None:
        return self.tasks.get_task(task_id)

    # ── Single image (async task) ─────────────────────────────────────────

    def submit_single(self, input_path: str, params: dict) -> str:
        """Start a single-image upscale task, returning its ``task_id``."""
        task_id = self.tasks.create_task()

        def _process(**kwargs):
            tm = kwargs['task_manager']
            tid = kwargs['task_id']
            result = self._upscale_one(input_path, params)
            tm.update_task(tid, progress=100)
            if not result.get('success'):
                tm.update_task(tid, status='error',
                               error=result.get('error') or 'Upscale failed')
                return []
            out = result['output_path']
            return [{'path': out, 'filename': os.path.basename(out)}]

        self.tasks.run_task(task_id, _process)
        return task_id

    def _upscale_one(self, input_path: str, params: dict) -> dict:
        """Upscale a single file to ``TMP/single/``. Returns result dict."""
        abs_input = os.path.realpath(input_path)
        if not os.path.isfile(abs_input):
            return {'success': False, 'output_path': None,
                    'error': f'Input file not found: {abs_input}'}
        if not _is_image_file(abs_input):
            return {'success': False, 'output_path': None,
                    'error': f'Unsupported image type: {abs_input}'}

        parsed, err = self.parse_params(params)
        if err:
            return {'success': False, 'output_path': None, 'error': err}

        single_dir = os.path.join(self.tmp_dir, 'single')
        os.makedirs(single_dir, exist_ok=True)
        ext = 'jpg' if parsed['output_format'] == 'jpg' else 'png'
        final_path = os.path.join(
            single_dir, f"out_{uuid.uuid4().hex}.{ext}")

        target_scale = parsed['target_scale']
        final_w, final_h = parsed['final_w'], parsed['final_h']

        # Dimension mode needs the effective scale computed from input size
        if final_w and final_h:
            final_w, final_h, effective_scale = _compute_dimension_upscale(
                abs_input, final_w, final_h, parsed['crop'])
            target_scale = effective_scale

        result = self._run_stages(
            abs_input, final_path, parsed, target_scale)

        if not result['success']:
            return result

        # Dimension mode: exact crop / fit adjustment
        if parsed['final_w'] and parsed['final_h']:
            pre = final_path
            final_path = os.path.join(
                single_dir, f"out_{uuid.uuid4().hex}.{ext}")
            if parsed['crop']:
                adj = self.resizer.crop(pre, final_path,
                                        parsed['final_w'], parsed['final_h'])
            else:
                adj = self.resizer.resize(pre, final_path,
                                          final_w, final_h)
            _cleanup_files(pre)
            if not adj['success']:
                return adj

        return {'success': True, 'output_path': final_path, 'error': None}

    def _run_stages(self, input_path: str, output_path: str,
                    parsed: dict, target_scale: float) -> dict:
        """Single or two-stage (blend) pipeline producing *output_path*."""
        model_2 = parsed['model_2']
        mix_ratio = parsed['mix_ratio']

        if model_2 and self.mixer and mix_ratio > 0:
            tmp1 = os.path.join(self.tmp_dir, f"stg1_{uuid.uuid4().hex}.png")
            tmp2 = os.path.join(self.tmp_dir, f"stg2_{uuid.uuid4().hex}.png")
            r1 = _run_upscale_pipeline(
                input_path, tmp1, model=parsed['model'],
                target_scale=target_scale,
                engine=self.engine, resizer=self.resizer, tmp_dir=self.tmp_dir)
            if not r1['success']:
                _cleanup_files(tmp1)
                return r1
            r2 = _run_upscale_pipeline(
                input_path, tmp2, model=model_2,
                target_scale=target_scale,
                engine=self.engine, resizer=self.resizer, tmp_dir=self.tmp_dir)
            if not r2['success']:
                _cleanup_files(tmp1, tmp2)
                return r2
            br = self.mixer.blend(tmp1, tmp2, output_path, ratio=mix_ratio)
            _cleanup_files(tmp1, tmp2)
            return br

        return _run_upscale_pipeline(
            input_path, output_path, model=parsed['model'],
            target_scale=target_scale,
            engine=self.engine, resizer=self.resizer, tmp_dir=self.tmp_dir)

    # ── Batch (multiple files, async) ─────────────────────────────────────

    def submit_files(self, files: list[str], params: dict) -> str:
        """Start a multi-file upscale task; results go to ``TMP/results/<id>``."""
        task_id = self.tasks.create_task()
        files = [os.path.realpath(f) for f in files if os.path.isfile(f)]

        def _process(**kwargs):
            tm = kwargs['task_manager']
            tid = kwargs['task_id']
            results_dir = os.path.join(self.tmp_dir, 'results', tid)
            os.makedirs(results_dir, exist_ok=True)

            parsed, err = self.parse_params(params)
            if err:
                tm.update_task(tid, status='error', error=err)
                return []

            results: list[dict] = []
            total = len(files)
            for idx, f in enumerate(files):
                base_name = os.path.splitext(os.path.basename(f))[0]
                out_name = f"{base_name}_x{int(parsed['target_scale'] or 2)}.png"
                out_path = os.path.join(results_dir, out_name)
                r = self._run_stages(f, out_path, parsed,
                                     parsed['target_scale'] or 2.0)
                if r['success']:
                    results.append({'path': out_path, 'filename': out_name})
                tm.update_task(tid, progress=int((idx + 1) / max(total, 1) * 100))
            return results

        self.tasks.run_task(task_id, _process)
        return task_id

    # ── Directory (async) ─────────────────────────────────────────────────

    def submit_dir(self, input_dir: str, output_dir: str | None,
                   params: dict) -> str:
        """Start a directory upscale task.

        Output goes to *output_dir* when given, else ``TMP/results/<id>``.
        """
        task_id = self.tasks.create_task()

        def _process(**kwargs):
            tm = kwargs['task_manager']
            tid = kwargs['task_id']
            resolved_input = os.path.realpath(input_dir)
            if not os.path.isdir(resolved_input):
                tm.update_task(tid, status='error',
                               error=f'Input directory not found: {input_dir}')
                return []

            parsed, err = self.parse_params(params)
            if err:
                tm.update_task(tid, status='error', error=err)
                return []

            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                results_dir = os.path.realpath(output_dir)
            else:
                results_dir = os.path.join(self.tmp_dir, 'results', tid)
                os.makedirs(results_dir, exist_ok=True)

            image_files = sorted(
                f for f in os.listdir(resolved_input) if _is_image_file(f))
            total = len(image_files)
            if total == 0:
                tm.update_task(tid, progress=100)
                return []

            results: list[dict] = []
            for idx, fname in enumerate(image_files):
                in_path = os.path.join(resolved_input, fname)
                base_name = os.path.splitext(fname)[0]
                out_name = f"{base_name}_x{int(parsed['target_scale'] or 2)}.png"
                out_path = os.path.join(results_dir, out_name)
                r = self._run_stages(in_path, out_path, parsed,
                                     parsed['target_scale'] or 2.0)
                if r['success']:
                    results.append({'path': out_path, 'filename': out_name})
                tm.update_task(tid, progress=int((idx + 1) / total * 100))
            return results

        self.tasks.run_task(task_id, _process)
        return task_id

    # ── Video (async) ─────────────────────────────────────────────────────

    def submit_video(self, video_path: str, params: dict) -> str:
        """Start a video upscale task; result goes to ``TMP/results/<id>``."""
        from subprocess import PIPE

        task_id = self.tasks.create_task()

        def _process(**kwargs):
            tm = kwargs['task_manager']
            tid = kwargs['task_id']
            abs_video = os.path.realpath(video_path)
            if not os.path.isfile(abs_video):
                tm.update_task(tid, status='error',
                               error=f'Video file not found: {video_path}')
                return []
            if not _is_video_file(abs_video):
                tm.update_task(tid, status='error',
                               error=f'Unsupported video format: {video_path}')
                return []

            parsed, err = self.parse_params(
                params, output_formats=VIDEO_OUTPUT_FORMATS)
            if err:
                tm.update_task(tid, status='error', error=err)
                return []
            output_format = parsed.get('output_format', 'mp4')

            # Dimension mode is resolved later (needs source frame size).
            scale = parsed['target_scale'] or 2.0
            dim_mode = bool(parsed['final_w'] and parsed['final_h'])

            results_dir = os.path.join(self.tmp_dir, 'results', tid)
            frames_dir = os.path.join(self.tmp_dir, 'frames', tid)
            out_frames_dir = os.path.join(self.tmp_dir, 'out_frames', tid)
            os.makedirs(results_dir, exist_ok=True)
            os.makedirs(frames_dir, exist_ok=True)
            os.makedirs(out_frames_dir, exist_ok=True)

            ffmpeg = self.resizer._ffmpeg_path
            ffmpeg_dir = os.path.dirname(ffmpeg)

            try:
                # ── 1. Extract frames (CFR to preserve timing) ───────────
                tm.update_task(tid, progress=2, status='extracting_frames')
                detected_fps = _detect_fps(ffmpeg_dir, abs_video)

                frame_pattern = os.path.join(frames_dir, 'frame%08d.jpg')
                extract_args = [
                    ffmpeg, '-i', abs_video,
                    '-qscale:v', '1',
                    '-fps_mode', 'cfr',      # ffmpeg 9.0: replaces -vsync cfr
                    '-r', str(detected_fps), '-start_number', '1', '-y',
                    frame_pattern,
                ]
                proc = popen(extract_args, stdout=PIPE, stderr=PIPE, shell=False)
                _, stderr = proc.communicate(timeout=600)
                if proc.returncode != 0:
                    err = stderr.decode('utf-8', errors='replace')[:500]
                    tm.update_task(tid, status='error',
                                   error=f'Frame extraction failed: {err}')
                    return []

                # ── 2. Enumerate frames ──────────────────────────────────
                frame_files = sorted(
                    f for f in os.listdir(frames_dir)
                    if f.lower().endswith(('.jpg', '.jpeg', '.png')))
                total_frames = len(frame_files)
                if total_frames == 0:
                    tm.update_task(tid, status='error',
                                   error='No frames extracted from video')
                    return []

                # ── 2b. Resolve dimension-mode targets (source-sized) ────
                # ``_compute_dimension_upscale`` needs an actual frame to read
                # the source resolution; frames are all the same size.
                video_final_w = video_final_h = None
                video_crop = False
                video_mid_w = video_mid_h = None
                if dim_mode:
                    first_frame = os.path.join(frames_dir, frame_files[0])
                    with Image.open(first_frame) as img:
                        src_w, src_h = img.size
                    video_final_w, video_final_h, eff_scale = (
                        _compute_dimension_upscale(
                            first_frame,
                            parsed['final_w'], parsed['final_h'],
                            parsed['crop'],
                        )
                    )
                    video_crop = parsed['crop']
                    scale = eff_scale
                    if video_crop:
                        # cover: 4x frame -> intermediate (fills target box)
                        # -> center-crop to exact final size. mid >= final.
                        cover_scale = max(
                            parsed['final_w'] / src_w,
                            parsed['final_h'] / src_h,
                        )
                        video_mid_w = max(1, round(src_w * cover_scale))
                        video_mid_h = max(1, round(src_h * cover_scale))
                    logger.info(
                        '[%s] video dimension mode: src %dx%d -> final %dx%d '
                        '(crop=%s, mid %sx%s)',
                        tid, src_w, src_h,
                        video_final_w, video_final_h, video_crop,
                        video_mid_w, video_mid_h,
                    )

                # ── 3. Model upscale ALL frames (dir batch + progress) ──
                model_4x_dir = os.path.join(self.tmp_dir, 'frames_4x', tid)

                def _on_progress(done, total):
                    pct = 8 + int((done / max(total, 1)) * 62)  # 8%→70%
                    tm.update_task(tid, progress=pct,
                                   status=f'upscaling_{done}_of_{total}')

                tm.update_task(tid, progress=8,
                               status=f'upscaling_0_of_{total_frames}')
                r = self.engine.upscale_dir_with_progress(
                    frames_dir, model_4x_dir,
                    total_frames=total_frames,
                    progress_callback=_on_progress,
                    model=parsed['model'], scale=4, output_format='jpg',
                    timeout=3600,
                )
                if not r['success']:
                    tm.update_task(tid, status='error',
                                   error=f'Frame upscale failed: {r["error"]}')
                    return []

                tm.update_task(tid, progress=70,
                               status=f'resizing_{total_frames}_frames')

                # ── 4. Resize each 4x frame to the final target ─────────
                model_4x_files = sorted(
                    f for f in os.listdir(model_4x_dir)
                    if f.lower().endswith(('.jpg', '.jpeg', '.png')))
                ffmpeg_scale = scale / 4.0
                for idx, fname in enumerate(model_4x_files):
                    in_frame = os.path.join(model_4x_dir, fname)
                    out_frame = os.path.join(out_frames_dir, fname)

                    if dim_mode:
                        if video_crop:
                            # cover: 4x -> mid (fills box) -> center-crop
                            tmp_mid = os.path.join(
                                out_frames_dir, f'.mid_{idx}.png')
                            rr = self.resizer.resize(
                                in_frame, tmp_mid,
                                video_mid_w, video_mid_h)
                            if rr['success']:
                                rr = self.resizer.crop(
                                    tmp_mid, out_frame,
                                    video_final_w, video_final_h)
                            _cleanup_files(tmp_mid)
                        else:
                            # contain: exact-size resize
                            rr = self.resizer.resize(
                                in_frame, out_frame,
                                video_final_w, video_final_h)
                    elif abs(ffmpeg_scale - 1.0) < 0.001:
                        # Target scale is 4x — model output is already correct
                        shutil.copy2(in_frame, out_frame)
                        rr = {'success': True, 'error': None}
                    else:
                        rr = self.resizer.resize_by_scale(
                            in_frame, out_frame, scale=ffmpeg_scale)

                    if not rr['success']:
                        tm.update_task(tid, status='error',
                                       error=f'Frame {idx+1} resize failed: {rr["error"]}')
                        return []
                    if total_frames > 0:
                        progress = 70 + int((idx + 1) / len(model_4x_files) * 25)
                        tm.update_task(tid, progress=progress,
                                       status=f'resizing_frame_{idx+1}')

                # ── 5. Merge frames into output video ────────────────────
                tm.update_task(tid, progress=95, status='merging_frames')
                shutil.rmtree(model_4x_dir, ignore_errors=True)

                out_ext = 'gif' if output_format == 'gif' else 'mp4'
                output_name = f"output.{out_ext}"
                output_path = os.path.join(results_dir, output_name)
                out_frame_pattern = os.path.join(out_frames_dir, 'frame%08d.jpg')

                if output_format == 'gif':
                    merge_args = [
                        ffmpeg, '-start_number', '1',
                        '-framerate', str(detected_fps),
                        '-i', out_frame_pattern,
                        '-vf', f'fps=10,scale=iw:ih:flags=lanczos,split[s0][s1];'
                               f'[s0]palettegen[p];[s1][p]paletteuse',
                        '-y', output_path,
                    ]
                else:
                    merge_args = [
                        ffmpeg, '-start_number', '1',
                        '-framerate', str(detected_fps),
                        '-i', out_frame_pattern,
                        '-i', abs_video,
                        '-map', '0:v:0', '-map', '1:a:0?',
                        '-c:a', 'copy', '-c:v', 'libx264',
                        '-r', str(detected_fps), '-pix_fmt', 'yuv420p',
                        '-shortest', '-y', output_path,
                    ]

                proc = popen(merge_args, stdout=PIPE, stderr=PIPE, shell=False)
                _, stderr = proc.communicate(timeout=600)
                if proc.returncode != 0:
                    err = stderr.decode('utf-8', errors='replace')[:500]
                    tm.update_task(tid, status='error',
                                   error=f'Frame merge failed: {err}')
                    return []

                return [{'path': output_path, 'filename': output_name}]

            except Exception as e:
                tm.update_task(tid, status='error', error=str(e))
                return []
            finally:
                shutil.rmtree(frames_dir, ignore_errors=True)
                shutil.rmtree(out_frames_dir, ignore_errors=True)

        self.tasks.run_task(task_id, _process)
        return task_id

    # ── Result helpers ────────────────────────────────────────────────────

    def zip_results(self, task_id: str, dest_zip: str) -> dict:
        """Package a task's result files into *dest_zip*.

        Returns ``{"success": bool, "zip_path": str, "error": str|None}``.
        """
        if not _VALID_TASK_ID_RE.match(task_id or ''):
            return {'success': False, 'zip_path': dest_zip,
                    'error': 'Invalid task id'}
        results_dir = os.path.join(self.tmp_dir, 'results', task_id)
        if not os.path.isdir(results_dir):
            return {'success': False, 'zip_path': dest_zip,
                    'error': 'Results not found'}

        files = sorted(
            f for f in os.listdir(results_dir)
            if os.path.isfile(os.path.join(results_dir, f)))
        if not files:
            return {'success': False, 'zip_path': dest_zip,
                    'error': 'No result files'}

        try:
            with zipfile.ZipFile(dest_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
                for fname in files:
                    zf.write(os.path.join(results_dir, fname), arcname=fname)
            return {'success': True, 'zip_path': dest_zip, 'error': None}
        except Exception as e:
            return {'success': False, 'zip_path': dest_zip, 'error': str(e)}
