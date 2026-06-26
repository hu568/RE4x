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
bp.models_dir = None    # path to script/models/
bp.task_manager = TaskManager()


# ── Helpers ───────────────────────────────────────────────────────────────

def _get_base_path() -> str:
    """Return the project root directory.

    - Frozen (PyInstaller): directory containing the executable.
    - Development: current working directory (``E:\\RE4x``).
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.realpath(sys.executable))
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

        ``file``     — image file (required)
        ``model``    — model name (default: ``realesr-animevideov3``)
        ``scale``    — upscale ratio (default: ``2``)
        ``model_2``  — second model for two-stage blend (optional)
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
    scale = float(request.form.get('scale', 2))
    model_2 = request.form.get('model_2')
    mix_ratio = float(request.form.get('mix_ratio', 0.5))

    # Normalise "None" sentinel from frontend
    if model_2 in (None, '', 'None'):
        model_2 = None

    engine = bp.engine
    mixer = bp.mixer

    # Directories we need to clean up when done
    to_clean = [saved_path]
    final_path: str | None = None

    try:
        # ── Two-stage blend ────────────────────────────────────────────────
        if model_2 and mixer and mix_ratio > 0:
            tmp1 = os.path.join(tmp_dir, f"stg1_{uuid.uuid4().hex}.png")
            tmp2 = os.path.join(tmp_dir, f"stg2_{uuid.uuid4().hex}.png")

            r1 = engine.upscale(saved_path, tmp1, model=model, scale=scale)
            if not r1['success']:
                _cleanup_files(tmp1)
                return jsonify({'error': f'Stage 1 upscale failed: {r1["error"]}'}), 500

            to_clean.append(tmp1)

            r2 = engine.upscale(saved_path, tmp2, model=model_2, scale=scale)
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
            result = engine.upscale(saved_path, final_path, model=model, scale=scale)
            if not result['success']:
                return jsonify({'error': f'Upscale failed: {result["error"]}'}), 500

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

                    r1 = bp.engine.upscale(input_path, tmp1, model=model, scale=scale)
                    if not r1['success']:
                        _cleanup_files(tmp1)
                        continue

                    r2 = bp.engine.upscale(input_path, tmp2, model=model_2, scale=scale)
                    if not r2['success']:
                        _cleanup_files(tmp1, tmp2)
                        continue

                    br = bp.mixer.blend(tmp1, tmp2, out_path, ratio=mix_ratio)
                    _cleanup_files(tmp1, tmp2)
                    if not br['success']:
                        continue
                else:
                    # ── Single stage ────────────────────────────────────────
                    r = bp.engine.upscale(input_path, out_path, model=model, scale=scale)
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

    # ── Path-traversal protection ──────────────────────────────────────────
    base_path = _get_base_path()
    project_root = os.path.realpath(base_path)

    try:
        resolved_input = os.path.realpath(input_dir)
    except (ValueError, OSError) as e:
        return jsonify({'error': f'Invalid input directory: {e}'}), 400

    # Normalise case for Windows before comparing
    if not os.path.normcase(resolved_input).startswith(
        os.path.normcase(project_root)
    ):
        return jsonify({'error': 'Path traversal denied: input_dir must be within project directory'}), 400

    if not os.path.isdir(resolved_input):
        return jsonify({'error': f'Input directory not found or not readable: {input_dir}'}), 400

    # ── Resolve output_dir (must also be within project root) ──────────────
    abs_output_dir: str | None = None
    if output_dir:
        try:
            abs_output_dir = os.path.realpath(output_dir)
            if not os.path.normcase(abs_output_dir).startswith(
                os.path.normcase(project_root)
            ):
                abs_output_dir = None  # fall back to TMP/results/<task_id>/
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

                    r1 = bp.engine.upscale(in_path, tmp1, model=model, scale=scale)
                    if not r1['success']:
                        _cleanup_files(tmp1)
                        continue

                    r2 = bp.engine.upscale(in_path, tmp2, model=model_2, scale=scale)
                    if not r2['success']:
                        _cleanup_files(tmp1, tmp2)
                        continue

                    br = bp.mixer.blend(tmp1, tmp2, out_path, ratio=mix_ratio)
                    _cleanup_files(tmp1, tmp2)
                    if not br['success']:
                        continue
                else:
                    r = bp.engine.upscale(in_path, out_path, model=model, scale=scale)
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
