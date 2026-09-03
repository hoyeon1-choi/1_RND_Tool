from __future__ import annotations

import logging
from pathlib import Path

from common.paths import LOGS_DIR, ensure_dir


def setup_logging(name: str, log_file: Path | None = None) -> logging.Logger:
    """Create a console and file logger with a consistent format."""
    ensure_dir(LOGS_DIR)
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    file_handler = logging.FileHandler(log_file or LOGS_DIR / f"{name}.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger

