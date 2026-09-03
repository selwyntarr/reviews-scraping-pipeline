"""Logging: console plus a daily-rotated file in LOG_DIR (default ./logs), kept 14 days.

Every stage and the scheduler share one file so a night's activity reads in order; each line carries
the stage/module name, and Run logs its run id at start and finish. httpx's per-request lines are
demoted to DEBUG so the file stays readable.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging() -> Path:
    log_dir = Path(os.environ.get("LOG_DIR", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "pipeline.log"
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    fmt = logging.Formatter(FORMAT)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)
    fh = TimedRotatingFileHandler(path, when="midnight", backupCount=14, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return path
