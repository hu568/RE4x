"""SD Enhance — Flask server entry point.

Usage:
    python server/main.py

Starts the server on http://localhost:5000 with all API routes registered.
The Web UI is served at the root URL (``/``) from ``templates/index.html``.

Path resolution:
    - Development (``python main.py``)    → ``os.getcwd()`` (project root)
    - Frozen (PyInstaller ``.exe``)       → directory of the executable
"""

import os
import sys

from flask import Flask, render_template


def create_app() -> Flask:
    """Build and configure the Flask application.

    Steps:
        1. Create the Flask app with a 50 MB upload limit.
        2. Resolve paths for engine, ffmpeg, and models (dev vs frozen).
        3. Initialise ``UpscaleEngine`` and ``ImageMixer``.
        4. Attach engine/mixer/models_dir to the API blueprint.
        5. Register the blueprint.
        6. Add the root route serving the Web UI.

    Returns:
        A fully configured Flask application instance.
    """
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB

    # ── Path resolution ───────────────────────────────────────────────────
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(os.path.realpath(sys.executable))
    else:
        base = os.getcwd()

    engine_path = os.path.join(base, 'script', 'realesrgan-ncnn-vulkan.exe')
    ffmpeg_path = os.path.join(base, 'script', 'ffmpeg.exe')
    models_dir = os.path.join(base, 'script', 'models')

    # ── Initialise engine & mixer ─────────────────────────────────────────
    from engine import UpscaleEngine  # noqa: PLC0415
    from mixer import ImageMixer      # noqa: PLC0415
    from routes import bp             # noqa: PLC0415

    engine = UpscaleEngine(engine_path, models_dir)
    mixer = ImageMixer(ffmpeg_path)

    # Attach shared instances to the blueprint
    bp.engine = engine
    bp.mixer = mixer
    bp.models_dir = models_dir

    app.register_blueprint(bp)

    # ── Root route: serve Web UI ──────────────────────────────────────────
    @app.route('/')
    def index():
        return render_template('index.html')

    return app


if __name__ == '__main__':
    application = create_app()
    print("SD Enhance server starting on http://localhost:5000")
    print(f"Engine: script{os.sep}realesrgan-ncnn-vulkan.exe")
    print(f"Models: script{os.sep}models{os.sep}")
    application.run(host='0.0.0.0', port=5000, debug=False)
