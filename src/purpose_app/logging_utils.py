# Lightweight logging facade so purpose_app.common and the Streamlit entry points
# emit structured events without each module managing file handlers.
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict


def _create_logger() -> logging.Logger:
    """Instantiate (or return) a JSON logger with rotating file handler fallback."""
    logger = logging.getLogger("purpose_app")
    if logger.handlers:
        return logger

    log_path = os.getenv("PURPOSE_LOG_PATH", "logs/purpose_app.log")
    try:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=5)
    except OSError:
        handler = logging.StreamHandler()

    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


_LOGGER = _create_logger()


def log_event(event_type: str, **payload: Any) -> None:
    """Emit structured telemetry without exposing logging internals to callers."""
    entry: Dict[str, Any] = {
        "event": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    entry.update(payload)
    try:
        _LOGGER.info(json.dumps(entry, ensure_ascii=False))
    except Exception:
        # Never let logging failures break the app
        _LOGGER.exception("Failed to log event", exc_info=True)
