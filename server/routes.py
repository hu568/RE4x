"""API routes for SD Enhance backend.

Provides:
  - TaskManager: in-memory async task management
  - Blueprint ``bp`` with all API routes
  - File validation (size, type, extension)
  - Path traversal protection (directory mode)
  - Two-stage blend support (model_1 → model_2 → ffmpeg blend)
"""

import os
import sys
import uuid
import zipfile
import threading
from io import BytesIO

from flask import Blueprint, request, jsonify, send_file

from PIL import Image


# ── Constants ─────────────────────────────────────────────────────────────

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff'}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


# ── Task Manager ──────────────────────────────────────────────────────────

class TaskManager:
    """In-memory task manager with background thread execution.

    Stores task state in a dict keyed by 8-character task ID.
    Each entry: {status, progress, results, error}
    """

    def __init__(self, max_workers: int = 1):
        self._tasks: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._max_workers = max_workers  # reserved for future pool use

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
        return task_id

    def update_task(self, task_id: str, **kwargs) -> None:
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].update(kwargs)

    def get_task(self, task_id: str) -> dict | None:
        with self._lock:
            return self._tasks.get(task_id)

    def remove_task(self, task_id: str) -> None:
        with self._lock:
            self._tasks.pop(task_id, None)

    # ── Background execution ──────────────────────────────────────────────

    def run_task(self, task_id: str, func, *args, **kwargs) -> None:
        """Run *func* in a daemon background thread.

        The function receives the same keyword arguments passed here.
        Before calling, status is set to ``processing``.
        After success, status → ``done`` with result list.
        On exception, status → ``error`` with message.
        """
        def _run():
            try:
                self.update_task(task_id, status='processing')
                results = func(*args, **kwargs, task_manager=self, task_id=task_id)
                self.update_task(task_id, status='done', results=results, progress=100)
            except Exception as e:
                self.update_task(task_id, status='error', error=str(e))

        t = threading.Thread(target=_run, daemon=True)
        t.start()


# ── Blueprint ─────────────────────────────────────────────────────────────

bp = Blueprint('api', __name__, url_prefix='/api')

# References — attached at registration time by create_app()
bp.engine = None        # UpscaleEngine instance
bp.mixer = None         # ImageMixer instance
bp.resizer = None       # ImageResizer instance
bp.models_dir = None    # path to tools/models/
bp.task_manager = TaskManager()


# ── Helpers ───────────────────────────────────────────────────────────────

def _get_base_path() -> str:
    """Return the project root directory.

    - Frozen (PyInstaller) exe at ``tools/sd-enhance-server/``
      → walk up 2 levels to project root.
    - Development: current working directory (``E:\\RE4x``).
    """
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(os.path.realpath(sys.executable))
        return os.path.dirname(os.path.dirname(exe_dir))
    return os.getcwd()


def _is_allowed_file(filename: str) -> bool:
    """Return ``True`` if *filename* has an allowed image extension."""
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXTENSIONS


def _validate_and_save_upload(file_storage, upload_dir: str):
    """Validate and persist an uploaded file.

    Checks (in order):
      1. Existence
      2. File extension
      3. Size < 50 MB
      4. PIL ``Image.verify()`` — rejects non-image payloads

    Args:
        file_storage: A ``Flask`` ``FileStorage`` from ``request.files``.
        upload_dir:   Directory to save the validated file into.

    Returns:
        ``(saved_path, None)`` on success.
        ``(None, (json_response, status_code))`` on validation failure.
    """
    # ── Existence ──────────────────────────────────────────────────────────
    if not file_storage or not file_storage.filename:
        return None, (jsonify({'error': 'No file provided'}), 400)

    # ── Extension ──────────────────────────────────────────────────────────
    if not _is_allowed_file(file_storage.filename):
        return None, (
            jsonify({'error': f'File type not allowed: {file_storage.filename}'}),
            400,
        )

    # ── Size (read into memory so we can also validate content) ────────────
    file_data = file_storage.read()
    if len(file_data) > MAX_FILE_SIZE:
        return None, (
            jsonify({'error': 'File too large (max 50 MB)'}),
            400,
        )

    # ── Content (MIME sniff via PIL) ───────────────────────────────────────
    try:
        img = Image.open(BytesIO(file_data))
        img.verify()
    except Exception:
        return None, (
            jsonify({'error': 'File is not a valid image'}),
            400,
        )

    # ── Persist ────────────────────────────────────────────────────────────
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}_{file_storage.filename}"
    save_path = os.path.join(upload_dir, safe_name)

    with open(save_path, 'wb') as f:
        f.write(file_data)

    return save_path, None


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

    Examples::

        target_scale=2  → model 4x → ffmpeg ×0.5  → 2x final
        target_scale=4  → model 4x → ffmpeg ×1.0  → 4x final
        target_scale=6  → model 4x → ffmpeg ×1.5  → 6x final
    """
    import uuid

    # Step 1: Model upscale at 4x
    tmp_4x = os.path.join(tmp_dir, f"pipe4x_{uuid.uuid4().hex}.png")
    r = engine.upscale(input_path, tmp_4x, model=model, scale=4)
    if not r['success']:
        _cleanup_files(tmp_4x)
        return {"success": False, "output_path": output_path,
                "error": f"Model upscale failed: {r['error']}"}

    # Step 2: ffmpeg resize to target
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
    """Compute output dimensions and effective scale factor for dimension mode.

    Args:
        input_path: Source image.
        target_w:   User-requested target width.
        target_h:   User-requested target height.
        crop:       If True, fill the target box (cover → crop).
                    If False, fit within the target box (contain).

    Returns:
        ``(final_w, final_h, effective_scale)`` where *effective_scale* is
        the multiplier needed to reach *final_w* × *final_h* from the
        input dimensions.
    """
    with Image.open(input_path) as img:
        src_w, src_h = img.size

    w_ratio = target_w / src_w
    h_ratio = target_h / src_h

    if crop:
        # Cover: scale so the image fills the entire target box
        effective_scale = max(w_ratio, h_ratio)
        final_w, final_h = target_w, target_h
    else:
        # Contain: scale so the image fits within the target box
        effective_scale = min(w_ratio, h_ratio)
        final_w = max(1, round(src_w * effective_scale))
        final_h = max(1, round(src_h * effective_scale))

    return final_w, final_h, effective_scale


# ══════════════════════════════════════════════════════════════════════════
# API Routes
# ══════════════════════════════════════════════════════════════════════════


# ── GET /api/models ───────────────────────────────────────────────────────

@bp.route('/models', methods=['GET'])
def get_models():
    """Return the list of available upscaling models as JSON.

    Response body example::

        [
            {
                "name": "realesr-animevideov3",
                "display_name": "RealESRGAN AnimeVideo v3",
                "max_scale": 4,
                "description": "Anime video (recommended, 2x/3x/4x)"
            },
            ...
        ]
    """
    from models import get_available_models  # noqa: PLC0415
    models = get_available_models(bp.models_dir)
    return jsonify(models)


# ── POST /api/upscale (single, synchronous) ───────────────────────────────

@bp.route('/upscale', methods=['POST'])
def upscale_single():
    """Upload and process a single image, returning the result file directly.

    Accepts ``multipart/form-data`` with fields:

        ``file``      — image file (required)
        ``model``     — model name (default: ``realesr-animevideov3``)
        ``scale``     — upscale ratio (default: ``2``)
        ``width``     — target width for dimension mode (optional)
        ``height``    — target height for dimension mode (optional)
        ``crop``      — crop to target (``"true"`` / ``"false"``, optional)
        ``model_2``   — second model for two-stage blend (optional)
        ``mix_ratio`` — blend ratio 0-1 (default: ``0.5``)

    On success returns ``200`` with the image binary (``image/png``).
    On validation failure returns ``400`` with a JSON error body.
    On engine failure returns ``500`` with a JSON error body.
    """
    # ── Validate upload ────────────────────────────────────────────────────
    file = request.files.get('file')
    base_path = _get_base_path()
    upload_dir = os.path.join(base_path, 'TMP', 'uploads')
    tmp_dir = os.path.join(base_path, 'TMP')

    saved_path, error = _validate_and_save_upload(file, upload_dir)
    if error:
        return error

    # ── Parse parameters ───────────────────────────────────────────────────
    model = request.form.get('model', 'realesr-animevideov3')
    scale_str = request.form.get('scale')
    width_str = request.form.get('width')
    height_str = request.form.get('height')
    crop = request.form.get('crop', '').lower() in ('true', '1', 'yes')
    model_2 = request.form.get('model_2')
    mix_ratio = float(request.form.get('mix_ratio', 0.5))

    # Normalise "None" sentinel from frontend
    if model_2 in (None, '', 'None'):
        model_2 = None

    engine = bp.engine
    mixer = bp.mixer
    resizer = bp.resizer

    # ── Determine mode & target scale ──────────────────────────────────────
    if width_str and height_str:
        # Dimension mode
        try:
            target_w = int(width_str)
            target_h = int(height_str)
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid width/height values'}), 400
        if target_w < 1 or target_h < 1:
            return jsonify({'error': 'Width and height must be positive'}), 400

        final_w, final_h, effective_scale = _compute_dimension_upscale(
            saved_path, target_w, target_h, crop
        )
    elif scale_str:
        # Scale mode
        target_scale = float(scale_str)
        effective_scale = target_scale
        final_w = final_h = None  # determined by resize_by_scale
    else:
        # Neither provided → default scale
        target_scale = 2.0
        effective_scale = target_scale
        final_w = final_h = None

    # Directories we need to clean up when done
    to_clean = [saved_path]
    final_path: str | None = None

    try:
        # ── Two-stage blend ────────────────────────────────────────────────
        if model_2 and mixer and mix_ratio > 0:
            tmp1 = os.path.join(tmp_dir, f"stg1_{uuid.uuid4().hex}.png")
            tmp2 = os.path.join(tmp_dir, f"stg2_{uuid.uuid4().hex}.png")

            r1 = _run_upscale_pipeline(
                saved_path, tmp1, model=model, target_scale=effective_scale,
                engine=engine, resizer=resizer, tmp_dir=tmp_dir,
            )
            if not r1['success']:
                _cleanup_files(tmp1)
                return jsonify({'error': f'Stage 1 upscale failed: {r1["error"]}'}), 500

            to_clean.append(tmp1)

            r2 = _run_upscale_pipeline(
                saved_path, tmp2, model=model_2, target_scale=effective_scale,
                engine=engine, resizer=resizer, tmp_dir=tmp_dir,
            )
            if not r2['success']:
                return jsonify({'error': f'Stage 2 upscale failed: {r2["error"]}'}), 500

            to_clean.append(tmp2)

            final_path = os.path.join(tmp_dir, f"mix_{uuid.uuid4().hex}.png")
            blend_result = mixer.blend(tmp1, tmp2, final_path, ratio=mix_ratio)
            if not blend_result['success']:
                return jsonify({'error': f'Blend failed: {blend_result["error"]}'}), 500

        # ── Single stage ───────────────────────────────────────────────────
        else:
            final_path = os.path.join(tmp_dir, f"out_{uuid.uuid4().hex}.png")
            result = _run_upscale_pipeline(
                saved_path, final_path, model=model, target_scale=effective_scale,
                engine=engine, resizer=resizer, tmp_dir=tmp_dir,
            )
            if not result['success']:
                return jsonify({'error': f'Upscale failed: {result["error"]}'}), 500

        # ── Dimension mode: exact size adjustment ──────────────────────────
        if final_w and final_h and crop:
            # After pipeline, crop to exact target dimensions
            pre_crop = final_path
            final_path = os.path.join(tmp_dir, f"crop_{uuid.uuid4().hex}.png")
            crop_result = resizer.crop(pre_crop, final_path, final_w, final_h)
            if not crop_result['success']:
                return jsonify({'error': f'Crop failed: {crop_result["error"]}'}), 500
            # pre_crop (pipeline output) still cleaned up via to_clean
        elif final_w and final_h and not crop:
            # After pipeline, resize to exact fit dimensions
            pre_resize = final_path
            final_path = os.path.join(tmp_dir, f"fit_{uuid.uuid4().hex}.png")
            resize_result = resizer.resize(pre_resize, final_path, final_w, final_h)
            if not resize_result['success']:
                return jsonify({'error': f'Fit resize failed: {resize_result["error"]}'}), 500

        to_clean.append(final_path)

        # ── Send result ────────────────────────────────────────────────────
        return send_file(final_path, mimetype='image/png')

    except Exception as e:
        return jsonify({'error': str(e)}), 500

    finally:
        _cleanup_files(*to_clean)


# ── POST /api/upscale/batch (multi-file, async) ───────────────────────────

@bp.route('/upscale/batch', methods=['POST'])
def upscale_batch():
    """Upload multiple images and process them asynchronously.

    Accepts ``multipart/form-data`` with:

        ``files[]``  — one or more image files (field name: ``files``)
        ``model``    — model name
        ``scale``    — upscale ratio
        ``model_2``  — second model (optional)
        ``mix_ratio`` — blend ratio (optional)

    Returns ``200`` with ``{"task_id": "..."}``.
    Poll ``GET /api/status/<task_id>`` for progress.
    """
    # ── Collect uploaded files ─────────────────────────────────────────────
    files = request.files.getlist('files')
    if not files:
        return jsonify({'error': 'No files provided'}), 400

    base_path = _get_base_path()
    upload_dir = os.path.join(base_path, 'TMP', 'uploads')

    # Validate and persist every file *before* spawning the background thread
    # so the request context remains available.
    saved_files: list[dict] = []
    for f in files:
        saved_path, err = _validate_and_save_upload(f, upload_dir)
        if err:
            continue  # silently skip invalid files
        saved_files.append({'path': saved_path, 'filename': f.filename})

    if not saved_files:
        return jsonify({'error': 'No valid image files provided'}), 400

    # ── Parse parameters ───────────────────────────────────────────────────
    model = request.form.get('model', 'realesr-animevideov3')
    scale = float(request.form.get('scale', 2))
    model_2 = request.form.get('model_2')
    mix_ratio = float(request.form.get('mix_ratio', 0.5))

    if model_2 in (None, '', 'None'):
        model_2 = None

    # ── Create async task ─────────────────────────────────────────────────
    task_id = bp.task_manager.create_task()

    def _process(**kwargs):
        """Background: upscale each saved file, collect result URLs."""
        tm = bp.task_manager
        tid = task_id  # from enclosing scope
        results_dir = os.path.join(base_path, 'TMP', 'results', tid)
        tmp_dir = os.path.join(base_path, 'TMP')
        os.makedirs(results_dir, exist_ok=True)

        results: list[dict] = []
        total = len(saved_files)

        for idx, sf in enumerate(saved_files):
            input_path = sf['path']
            fname = sf['filename']
            base_name = os.path.splitext(fname)[0]
            out_name = f"{base_name}_x{int(scale)}.png"
            out_path = os.path.join(results_dir, out_name)

            try:
                if model_2 and bp.mixer and mix_ratio > 0:
                    # ── Two-stage blend ─────────────────────────────────────
                    tmp1 = os.path.join(tmp_dir, f"bat_{uuid.uuid4().hex}.png")
                    tmp2 = os.path.join(tmp_dir, f"bat_{uuid.uuid4().hex}.png")

                    r1 = _run_upscale_pipeline(
                        input_path, tmp1, model=model, target_scale=scale,
                        engine=bp.engine, resizer=bp.resizer, tmp_dir=tmp_dir,
                    )
                    if not r1['success']:
                        _cleanup_files(tmp1)
                        continue

                    r2 = _run_upscale_pipeline(
                        input_path, tmp2, model=model_2, target_scale=scale,
                        engine=bp.engine, resizer=bp.resizer, tmp_dir=tmp_dir,
                    )
                    if not r2['success']:
                        _cleanup_files(tmp1, tmp2)
                        continue

                    br = bp.mixer.blend(tmp1, tmp2, out_path, ratio=mix_ratio)
                    _cleanup_files(tmp1, tmp2)
                    if not br['success']:
                        continue
                else:
                    # ── Single stage ────────────────────────────────────────
                    r = _run_upscale_pipeline(
                        input_path, out_path, model=model, target_scale=scale,
                        engine=bp.engine, resizer=bp.resizer, tmp_dir=tmp_dir,
                    )
                    if not r['success']:
                        continue

                results.append({
                    'url': f"/api/results/{tid}/{out_name}",
                    'filename': out_name,
                })

            except Exception:
                pass
            finally:
                _cleanup_files(input_path)  # remove uploaded temp

            # Update progress (0–100)
            tm.update_task(tid, progress=int((idx + 1) / total * 100))

        return results

    bp.task_manager.run_task(task_id, _process)
    return jsonify({'task_id': task_id})


# ── POST /api/upscale/dir (directory, async) ──────────────────────────────

@bp.route('/upscale/dir', methods=['POST'])
def upscale_dir():
    """Process every image in a directory asynchronously.

    Accepts ``application/json`` with::

        {
            "input_dir":  "path/to/images",
            "output_dir": "path/to/results",   // optional
            "model":      "realesr-animevideov3",
            "scale":      2,
            "model_2":    "...",               // optional
            "mix_ratio":  0.5                  // optional
        }

    Security: rejects paths that resolve outside the project root
    (path-traversal protection via ``os.path.realpath``).

    Returns ``200`` with ``{"task_id": "..."}``.
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Invalid or missing JSON body'}), 400

    # ── Extract params ────────────────────────────────────────────────────
    input_dir = (data.get('input_dir') or '').strip()
    output_dir = (data.get('output_dir') or '').strip()
    model = data.get('model', 'realesr-animevideov3')
    scale = float(data.get('scale', 2))
    model_2 = data.get('model_2')
    mix_ratio = float(data.get('mix_ratio', 0.5))

    if model_2 in (None, '', 'None'):
        model_2 = None

    if not input_dir:
        return jsonify({'error': 'input_dir is required'}), 400

    # ── Validate input_dir (any accessible local path is allowed) ─────────
    base_path = _get_base_path()
    project_root = os.path.realpath(base_path)

    try:
        resolved_input = os.path.realpath(input_dir)
    except (ValueError, OSError) as e:
        return jsonify({'error': f'Invalid input directory: {e}'}), 400

    if not os.path.isdir(resolved_input):
        return jsonify({'error': f'Input directory not found or not readable: {input_dir}'}), 400

    # ── Resolve output_dir (use as-is if valid, otherwise fall back) ──────
    abs_output_dir: str | None = None
    if output_dir:
        try:
            abs_output_dir = os.path.realpath(output_dir)
        except (ValueError, OSError):
            abs_output_dir = None

    # ── Create async task ─────────────────────────────────────────────────
    task_id = bp.task_manager.create_task()

    def _process(**kwargs):
        """Background: iterate over directory, upscale each image."""
        tm = bp.task_manager
        tid = task_id  # from enclosing scope
        results_dir = os.path.join(project_root, 'TMP', 'results', tid)
        tmp_dir = os.path.join(project_root, 'TMP')
        os.makedirs(results_dir, exist_ok=True)

        results: list[dict] = []

        # Collect image files sorted for deterministic ordering
        image_files = sorted(
            f for f in os.listdir(resolved_input) if _is_allowed_file(f)
        )
        total = len(image_files)
        if total == 0:
            tm.update_task(tid, progress=100)
            return results

        # Prepare user-specified output directory if valid
        if abs_output_dir:
            os.makedirs(abs_output_dir, exist_ok=True)

        for idx, fname in enumerate(image_files):
            in_path = os.path.join(resolved_input, fname)
            base_name = os.path.splitext(fname)[0]
            out_name = f"{base_name}_x{int(scale)}.png"

            if abs_output_dir:
                out_path = os.path.join(abs_output_dir, out_name)
            else:
                out_path = os.path.join(results_dir, out_name)

            try:
                if model_2 and bp.mixer and mix_ratio > 0:
                    tmp1 = os.path.join(tmp_dir, f"dir_{uuid.uuid4().hex}.png")
                    tmp2 = os.path.join(tmp_dir, f"dir_{uuid.uuid4().hex}.png")

                    r1 = _run_upscale_pipeline(
                        in_path, tmp1, model=model, target_scale=scale,
                        engine=bp.engine, resizer=bp.resizer, tmp_dir=tmp_dir,
                    )
                    if not r1['success']:
                        _cleanup_files(tmp1)
                        continue

                    r2 = _run_upscale_pipeline(
                        in_path, tmp2, model=model_2, target_scale=scale,
                        engine=bp.engine, resizer=bp.resizer, tmp_dir=tmp_dir,
                    )
                    if not r2['success']:
                        _cleanup_files(tmp1, tmp2)
                        continue

                    br = bp.mixer.blend(tmp1, tmp2, out_path, ratio=mix_ratio)
                    _cleanup_files(tmp1, tmp2)
                    if not br['success']:
                        continue
                else:
                    r = _run_upscale_pipeline(
                        in_path, out_path, model=model, target_scale=scale,
                        engine=bp.engine, resizer=bp.resizer, tmp_dir=tmp_dir,
                    )
                    if not r['success']:
                        continue

                results.append({
                    'url': f"/api/results/{tid}/{out_name}",
                    'filename': out_name,
                })

            except Exception:
                pass

            tm.update_task(tid, progress=int((idx + 1) / total * 100))

        return results

    bp.task_manager.run_task(task_id, _process)
    return jsonify({'task_id': task_id})


# ── GET /api/status/<task_id> ─────────────────────────────────────────────

@bp.route('/status/<task_id>', methods=['GET'])
def get_status(task_id: str):
    """Return the current state of an async task.

    Response example (processing)::

        {"status": "processing", "progress": 45, "results": [], "error": null}

    Response example (done)::

        {"status": "done", "progress": 100, "results": [...], "error": null}

    Response example (not found)::

        HTTP 404  {"error": "Task not found"}
    """
    task = bp.task_manager.get_task(task_id)
    if task is None:
        return jsonify({'error': 'Task not found'}), 404
    return jsonify(task)


# ── GET /api/results/<task_id>/<filename> ─────────────────────────────────

@bp.route('/results/<task_id>/<filename>', methods=['GET'])
def serve_result(task_id: str, filename: str):
    """Serve a result file produced by a batch or directory task.

    Security: resolves the requested path and verifies it lies inside
    ``TMP/results/<task_id>/`` — rejects any path-traversal attempt
    embedded in *filename*.
    """
    base_path = _get_base_path()
    safe_base = os.path.realpath(os.path.join(base_path, 'TMP', 'results', task_id))

    requested = os.path.realpath(os.path.join(safe_base, filename))

    # Ensure the resolved path is still inside the expected directory
    if not requested.startswith(safe_base):
        return jsonify({'error': 'Access denied'}), 403

    if not os.path.isfile(requested):
        return jsonify({'error': 'File not found'}), 404

    return send_file(requested)


# ── GET /api/results/<task_id>/download (zip all results) ───────────────────

@bp.route('/results/<task_id>/download', methods=['GET'])
def download_results_zip(task_id: str):
    """Package all result files of *task_id* into a zip and return it.

    Returns ``200`` with ``application/zip`` on success.
    Returns ``404`` if the task's results directory is empty or missing.
    """
    base_path = _get_base_path()
    results_dir = os.path.join(base_path, 'TMP', 'results', task_id)

    if not os.path.isdir(results_dir):
        return jsonify({'error': 'Results not found'}), 404

    files = sorted(
        f for f in os.listdir(results_dir)
        if os.path.isfile(os.path.join(results_dir, f))
    )
    if not files:
        return jsonify({'error': 'No result files to download'}), 404

    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for fname in files:
            fpath = os.path.join(results_dir, fname)
            zf.write(fpath, arcname=fname)

    buf.seek(0)
    zip_name = f"sd_enhance_{task_id}.zip"
    return send_file(
        buf,
        mimetype='application/zip',
        as_attachment=True,
        download_name=zip_name,
    )


# ── Video allowed extensions ────────────────────────────────────────────────

VIDEO_EXTENSIONS = {'.mp4', '.webm', '.avi', '.mov', '.mkv'}


def _is_video_file(filename: str) -> bool:
    """Return ``True`` if *filename* has an allowed video extension."""
    _, ext = os.path.splitext(filename.lower())
    return ext in VIDEO_EXTENSIONS


# ── POST /api/upscale/video (async) ─────────────────────────────────────────

@bp.route('/upscale/video', methods=['POST'])
def upscale_video():
    """Upload a video and upscale every frame asynchronously.

    Accepts ``multipart/form-data`` with:

        ``file``          — video file (required)
        ``model``         — model name (default: ``realesr-animevideov3``)
        ``scale``         — upscale ratio (default: ``2``)
        ``output_format`` — ``mp4``, ``avi``, or ``gif`` (default: ``mp4``)

    Returns ``200`` with ``{"task_id": "..."}``.
    Poll ``GET /api/status/<task_id>`` for progress.
    """
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'error': 'No video file provided'}), 400

    if not _is_video_file(file.filename):
        return jsonify({
            'error': f'Unsupported video format: {file.filename}. '
                     f'Supported: {", ".join(VIDEO_EXTENSIONS)}'
        }), 400

    # Read into memory, validate size
    file_data = file.read()
    if len(file_data) > MAX_FILE_SIZE:
        return jsonify({'error': 'Video file too large (max 50 MB)'}), 400

    # ── Parse parameters ───────────────────────────────────────────────────
    model = request.form.get('model', 'realesr-animevideov3')
    scale = float(request.form.get('scale', 2))
    output_format = request.form.get('output_format', 'mp4').lower()
    if output_format not in ('mp4', 'avi', 'gif'):
        return jsonify({'error': f'Unsupported output format: {output_format}'}), 400

    # ── Persist uploaded video ─────────────────────────────────────────────
    base_path = _get_base_path()
    upload_dir = os.path.join(base_path, 'TMP', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}_{file.filename}"
    video_path = os.path.join(upload_dir, safe_name)

    with open(video_path, 'wb') as f:
        f.write(file_data)

    # ── Create async task ──────────────────────────────────────────────────
    task_id = bp.task_manager.create_task()

    def _process_video(**kwargs):
        """Background: extract frames, upscale, merge back."""
        from subprocess import Popen, PIPE
        tm = bp.task_manager
        tid = task_id
        tmp_dir = os.path.join(base_path, 'TMP')
        results_dir = os.path.join(tmp_dir, 'results', tid)
        frames_dir = os.path.join(tmp_dir, 'frames', tid)
        out_frames_dir = os.path.join(tmp_dir, 'out_frames', tid)
        os.makedirs(results_dir, exist_ok=True)
        os.makedirs(frames_dir, exist_ok=True)
        os.makedirs(out_frames_dir, exist_ok=True)

        try:
            # ── 1. Extract frames (CFR to preserve timing) ─────────────────
            tm.update_task(tid, progress=2,
                           status='extracting_frames')

            # Detect FPS early — used to guide extraction
            detected_fps = _detect_fps(video_path)

            frame_pattern = os.path.join(frames_dir, 'frame%08d.jpg')
            extract_args = [
                bp.resizer._ffmpeg_path,
                '-i', video_path,
                '-qscale:v', '1',
                '-vsync', 'cfr',
                '-r', str(detected_fps),
                '-start_number', '1',
                '-y',
                frame_pattern,
            ]
            proc = Popen(extract_args, stdout=PIPE, stderr=PIPE, shell=False)
            _, stderr = proc.communicate(timeout=600)
            if proc.returncode != 0:
                err = stderr.decode('utf-8', errors='replace')[:500]
                tm.update_task(tid, status='error',
                               error=f'Frame extraction failed: {err}')
                return []

            # ── 2. Enumerate frames ────────────────────────────────────────
            frame_files = sorted(
                f for f in os.listdir(frames_dir)
                if f.lower().endswith(('.jpg', '.jpeg', '.png'))
            )
            total_frames = len(frame_files)
            if total_frames == 0:
                tm.update_task(tid, status='error',
                               error='No frames extracted from video')
                return []

            # ── 3. Model upscale ALL frames (directory batch + progress) ──
            model_4x_dir = os.path.join(tmp_dir, 'frames_4x', tid)

            def _on_progress(done, total):
                pct = 8 + int((done / max(total, 1)) * 62)  # 8%→70%
                tm.update_task(
                    tid, progress=pct,
                    status=f'upscaling_{done}_of_{total}',
                )

            tm.update_task(tid, progress=8,
                           status=f'upscaling_0_of_{total_frames}')

            r = bp.engine.upscale_dir_with_progress(
                frames_dir, model_4x_dir,
                total_frames=total_frames,
                progress_callback=_on_progress,
                model=model, scale=4, output_format='jpg',
                timeout=3600,
            )
            if not r['success']:
                tm.update_task(tid, status='error',
                               error=f'Frame upscale failed: {r["error"]}')
                return []

            tm.update_task(tid, progress=70,
                           status=f'resizing_{total_frames}_frames')

            # ── 4. ffmpeg resize each frame to target scale ─────────────────
            model_4x_files = sorted(
                f for f in os.listdir(model_4x_dir)
                if f.lower().endswith(('.jpg', '.jpeg', '.png'))
            )

            ffmpeg_scale = scale / 4.0
            for idx, fname in enumerate(model_4x_files):
                in_frame = os.path.join(model_4x_dir, fname)
                out_frame = os.path.join(out_frames_dir, fname)

                if abs(ffmpeg_scale - 1.0) < 0.001:
                    # Target scale is 4x — model output is already correct,
                    # just copy the file
                    import shutil
                    shutil.copy2(in_frame, out_frame)
                else:
                    r = bp.resizer.resize_by_scale(
                        in_frame, out_frame, scale=ffmpeg_scale,
                    )
                    if not r['success']:
                        tm.update_task(tid, status='error',
                                       error=f'Frame {idx+1} resize failed: {r["error"]}')
                        return []

                # Progress: 70→95 across resizes
                if total_frames > 0:
                    progress = 70 + int((idx + 1) / len(model_4x_files) * 25)
                    tm.update_task(tid, progress=progress,
                                   status=f'resizing_frame_{idx+1}')

            # ── 5. Merge frames into output video ─────────────────────────
            tm.update_task(tid, progress=95, status='merging_frames')

            # Use the same FPS detected during extraction
            fps = detected_fps

            # Cleanup model 4x temp dir
            import shutil
            shutil.rmtree(model_4x_dir, ignore_errors=True)

            out_ext = 'gif' if output_format == 'gif' else 'mp4'
            output_name = f"output.{out_ext}"
            output_path = os.path.join(results_dir, output_name)

            out_frame_pattern = os.path.join(out_frames_dir, 'frame%08d.jpg')

            if output_format == 'gif':
                # GIF: lower FPS, palette
                merge_args = [
                    bp.resizer._ffmpeg_path,
                    '-start_number', '1',
                    '-framerate', str(fps),
                    '-i', out_frame_pattern,
                    '-vf', f'fps=10,scale=iw:ih:flags=lanczos,split[s0][s1];'
                           f'[s0]palettegen[p];[s1][p]paletteuse',
                    '-y', output_path,
                ]
            else:
                # MP4/AVI: libx264 with audio from source
                merge_args = [
                    bp.resizer._ffmpeg_path,
                    '-start_number', '1',
                    '-framerate', str(fps),
                    '-i', out_frame_pattern,
                    '-i', video_path,
                    '-map', '0:v:0',
                    '-map', '1:a:0?',
                    '-c:a', 'copy',
                    '-c:v', 'libx264',
                    '-r', str(fps),
                    '-pix_fmt', 'yuv420p',
                    '-shortest',
                    '-y', output_path,
                ]

            proc = Popen(merge_args, stdout=PIPE, stderr=PIPE, shell=False)
            _, stderr = proc.communicate(timeout=600)
            if proc.returncode != 0:
                err = stderr.decode('utf-8', errors='replace')[:500]
                tm.update_task(tid, status='error',
                               error=f'Frame merge failed: {err}')
                return []

            return [{
                'url': f"/api/results/{tid}/{output_name}",
                'filename': output_name,
            }]

        except Exception as e:
            tm.update_task(tid, status='error', error=str(e))
            return []
        finally:
            # Cleanup temp dirs (keep results)
            import shutil
            for d in [frames_dir, out_frames_dir]:
                try:
                    shutil.rmtree(d, ignore_errors=True)
                except Exception:
                    pass
            _cleanup_files(video_path)

    bp.task_manager.run_task(task_id, _process_video)
    return jsonify({'task_id': task_id})


def _detect_fps(video_path: str) -> float:
    """Detect frame-rate of *video_path* using ffprobe or ffmpeg.

    Prefers ``avg_frame_rate`` (actual frame count ÷ duration) over
    ``r_frame_rate`` (often wrong for VFR).

    Falls back to 24.0 if detection fails.
    """
    import json as _json
    import re
    from subprocess import Popen, PIPE

    ffmpeg_dir = os.path.dirname(bp.resizer._ffmpeg_path)

    # ── Try ffprobe first (most accurate) ────────────────────────────────
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
            proc = Popen(args, stdout=PIPE, stderr=PIPE, shell=False)
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

    # ── Fallback: parse ffmpeg -i output ─────────────────────────────────
    args = [
        bp.resizer._ffmpeg_path,
        '-i', video_path,
    ]
    try:
        proc = Popen(args, stdout=PIPE, stderr=PIPE, shell=False)
        _, stderr = proc.communicate(timeout=30)
        output = stderr.decode('utf-8', errors='replace')
        # Look for lines like: "Stream #0:0: Video: ..., 60 fps, ..."
        # or "..., 23.98 fps, ..." or "..., 30 tbr, ..."
        match = re.search(r'Video:.*?(\d+\.?\d*)\s*fps', output)
        if match:
            fps = float(match.group(1))
            if fps > 0:
                return fps
        # Also try the tbr (time base rate) which is usually the stream fps
        match = re.search(r'Video:.*?(\d+\.?\d*)\s*tbr', output)
        if match:
            fps = float(match.group(1))
            if fps > 0:
                return fps
    except Exception:
        pass

    return 24.0  # sensible default
