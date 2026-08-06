"""Shared logging setup for the SD Enhance desktop app.

Everything is logged to ``<project root>/logs/sd-enhance.log`` with daily
rotation (keep 7 days). In frozen mode the project root is the exe's
directory, so logs are written next to the executable — easy to find and
inspect when the user reports a problem.

Usage::

    import logging
    logger = logging.getLogger('sd_enhance.core')
    logger.info(...)

Call :func:`setup_logging` once from the app entry point (or tests).
"""

import logging
import os
from logging.handlers import TimedRotatingFileHandler

# Module-level logger used by core / engine / mixer / resizer / gui_api.
logger = logging.getLogger('sd_enhance')

_FORMAT = (
    '%(asctime)s | %(levelname)-7s | %(name)s | %(message)s'
)
_DATEFMT = '%Y-%m-%d %H:%M:%S'


def log_dir(base_path: str | None = None) -> str:
    """Return the ``logs`` directory (created on demand)."""
    root = base_path or os.getcwd()
    return os.path.join(root, 'logs')


def setup_logging(base_path: str | None = None,
                  level: int = logging.DEBUG) -> str:
    """Configure root ``sd_enhance`` logger; returns the log file path.

    Idempotent — safe to call from tests and the app entry point.
    """
    root = logging.getLogger('sd_enhance')
    if getattr(root, '_sd_enhance_configured', False):
        return os.path.join(log_dir(base_path), 'sd-enhance.log')

    logs = log_dir(base_path)
    os.makedirs(logs, exist_ok=True)
    log_file = os.path.join(logs, 'sd-enhance.log')

    root.setLevel(level)

    # File handler (daily rotation, keep 7 days)
    fh = TimedRotatingFileHandler(
        log_file, when='midnight', backupCount=7, encoding='utf-8')
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))
    root.addHandler(fh)

    # Console handler (helpful in dev / tests)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(_FORMAT, _DATEFMT))
    root.addHandler(ch)

    root._sd_enhance_configured = True  # type: ignore[attr-defined]
    return log_file
