"""Structured JSON logging with file rotation and per-task categorization (v4.16).

Writes rotation-managed log files to LOG_DIR (default /app/thumbnail_cache/logs/).
Each log entry is a JSON line with: timestamp, level, task, message, and optional
extra fields (file, duration_ms, error, user_agent, etc.).

Usage in other modules:
    from .pipeline_logging import get_logger
    log = get_logger("thumbnail")
    log.info("Generated thumbnail", file="DSS2/xyz.fits", duration_ms=45)
    log.error("Source detection failed", file="...", error=str(e))

Docker logs still receive console output (stderr) via a separate handler.
JSON log files are persisted across container restarts (mounted volume).
"""
import json
import logging
import os
import sys
import time
import threading
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────
LOG_DIR = Path(os.getenv("PIPELINE_LOG_DIR", "/app/thumbnail_cache/logs"))
LOG_LEVEL = os.getenv("PIPELINE_LOG_LEVEL", "INFO")
LOG_MAX_DAYS = int(os.getenv("PIPELINE_LOG_MAX_DAYS", "30"))
LOG_MAX_SIZE_MB = int(os.getenv("PIPELINE_LOG_MAX_SIZE_MB", "100"))
JSON_LOGGING_ENABLED = os.getenv("PIPELINE_JSON_LOGGING", "true").lower() == "true"


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON for machine parsing."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "task": getattr(record, "task", record.name),
            "msg": record.getMessage(),
        }

        # Include extra fields if present
        for key in ("file", "duration_ms", "error", "user_agent",
                     "file_size_mb", "source_count", "cache_hit"):
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val

        # Include exception info if present
        if record.exc_info and record.exc_info[0]:
            entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(entry, ensure_ascii=False, default=str)


class SizeAndTimeRotatingHandler(logging.Handler):
    """Rotate logs daily AND when size exceeds limit. Thread-safe.

    Each task category gets its own log file:
      - pipeline.log       (general)
      - thumbnail.log      (thumbnail generation)
      - source_detect.log  (source detection)
      - llm.log            (LLM proxy)
      - fits_io.log        (FITS read/write)
    """

    def __init__(self, log_dir: Path, task: str = "pipeline",
                 max_days: int = 30, max_size_bytes: int = 100 * 1024 * 1024):
        super().__init__()
        self.log_dir = Path(log_dir)
        self.task = task
        self.max_days = max_days
        self.max_size_bytes = max_size_bytes
        self._lock = threading.Lock()
        self._current_date = None
        self._file = None
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _get_log_path(self) -> Path:
        today = datetime.now().strftime("%Y%m%d")
        return self.log_dir / f"{self.task}-{today}.log"

    def _rotate_if_needed(self):
        today = datetime.now().strftime("%Y%m%d")
        log_path = self._get_log_path()

        # Daily rotation
        if today != self._current_date:
            self._current_date = today
            if self._file:
                self._file.close()
            self._file = open(str(log_path), "a", encoding="utf-8")

        # Size-based rotation
        if self._file:
            try:
                size = self._file.tell()
                if size > self.max_size_bytes:
                    self._file.close()
                    # Rename old file
                    backup = log_path.with_suffix(f".{int(time.time())}.log")
                    log_path.rename(backup)
                    self._file = open(str(log_path), "a", encoding="utf-8")
                    # Cleanup: remove old rotated files beyond max_days
                    self._cleanup_old()
            except OSError:
                pass

    def _cleanup_old(self):
        """Remove log files older than max_days."""
        try:
            cutoff = time.time() - self.max_days * 86400
            for log_file in self.log_dir.glob(f"{self.task}-*.log*"):
                if log_file.stat().st_mtime < cutoff:
                    try:
                        log_file.unlink()
                    except OSError:
                        pass
        except OSError:
            pass

    def emit(self, record: logging.LogRecord):
        if not JSON_LOGGING_ENABLED:
            return
        try:
            with self._lock:
                self._rotate_if_needed()
                if self._file:
                    msg = self.format(record)
                    self._file.write(msg + "\n")
                    self._file.flush()
        except Exception:
            self.handleError(record)

    def close(self):
        with self._lock:
            if self._file:
                self._file.close()
                self._file = None
        super().close()


# ── Logger factory ─────────────────────────────────────────────────────
_loggers: dict[str, logging.Logger] = {}
_setup_lock = threading.Lock()


def get_logger(task: str = "pipeline") -> logging.Logger:
    """Get or create a structured logger for a specific task category.

    Args:
        task: Task category — "thumbnail", "source_detect", "llm", "fits_io", "general"

    Returns:
        A configured logger that writes JSON to file AND human-readable to stderr.
    """
    with _setup_lock:
        if task in _loggers:
            return _loggers[task]

        logger = logging.getLogger(f"pipeline.{task}")
        logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
        logger.propagate = False  # Don't double-log to root logger

        # Clear any existing handlers (idempotent)
        logger.handlers.clear()

        # File handler: JSON structured logs
        file_handler = SizeAndTimeRotatingHandler(
            LOG_DIR, task=task,
            max_days=LOG_MAX_DAYS,
            max_size_bytes=LOG_MAX_SIZE_MB * 1024 * 1024,
        )
        file_handler.setFormatter(JsonFormatter())
        file_handler.setLevel(logging.DEBUG)  # File gets all levels
        logger.addHandler(file_handler)

        # Console handler: human-readable for Docker logs
        console = logging.StreamHandler(sys.stderr)
        console.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
        console_fmt = logging.Formatter(
            f'[%(asctime)s] [{task}] %(levelname)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )
        console.setFormatter(console_fmt)
        logger.addHandler(console)

        _loggers[task] = logger
        return logger


def log_task(task: str, level: str, message: str, **extra):
    """Convenience: log a single message with extra fields without creating a logger.

    Example:
        log_task("source_detect", "info", "Detection complete",
                 file="DSS2/xyz.fits", source_count=42, duration_ms=350)
    """
    log = get_logger(task)
    log_fn = getattr(log, level.lower(), log.info)
    # Attach extra fields to the log record via a custom adapter
    extra_dict = {k: v for k, v in extra.items() if v is not None}
    log_fn(message, extra=extra_dict) if extra_dict else log_fn(message)


# Initialize root logger on module import
_root_log = get_logger("pipeline")
_root_log.info(
    "Pipeline logging initialized",
    extra={"log_dir": str(LOG_DIR), "level": LOG_LEVEL,
           "json_enabled": JSON_LOGGING_ENABLED, "max_days": LOG_MAX_DAYS}
)
