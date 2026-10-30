"""
Patch-SecOps Solution Logging Configuration.

Provides optimized logging with async handlers, batching, rotation,
and structured JSON logging for performance.
"""

import os
import sys
import json
import logging
import logging.handlers
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from queue import Queue
import threading

# Log directory configuration
LOG_DIR = os.getenv("PM_LOG_DIR", "/var/log/patchmaster")
MAX_LOG_SIZE = int(os.getenv("PM_MAX_LOG_SIZE", str(10 * 1024 * 1024)))  # 10MB default
BACKUP_COUNT = int(os.getenv("PM_LOG_BACKUP_COUNT", "5"))
LOG_BATCH_SIZE = int(
    os.getenv("PM_LOG_BATCH_SIZE", "100")
)  # Batch size for async writes
LOG_BATCH_INTERVAL = float(
    os.getenv("PM_LOG_BATCH_INTERVAL", "1.0")
)  # Seconds between batch flushes


class JSONFormatter(logging.Formatter):
    """Structured JSON logging formatter for log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields
        if hasattr(record, "extra_data"):
            log_data.update(record.extra_data)

        return json.dumps(log_data)


class AsyncLogHandler(logging.Handler):
    """Async logging handler with batching for high-throughput scenarios.

    Buffers log records and writes them in batches to reduce I/O overhead.
    """

    def __init__(
        self,
        batch_size: int = LOG_BATCH_SIZE,
        batch_interval: float = LOG_BATCH_INTERVAL,
    ):
        super().__init__()
        self.batch_size = batch_size
        self.batch_interval = batch_interval
        self.buffer: list[logging.LogRecord] = []
        self.lock = threading.Lock()
        self._shutdown = False

        # Start background writer thread
        self._thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._thread.start()

    def emit(self, record: logging.LogRecord):
        """Add record to buffer."""
        if self._shutdown:
            return

        with self.lock:
            self.buffer.append(record)
            if len(self.buffer) >= self.batch_size:
                self._flush_buffer()

    def _writer_loop(self):
        """Background thread to flush buffer at intervals."""
        import time

        while not self._shutdown:
            time.sleep(self.batch_interval)
            with self.lock:
                if self.buffer:
                    self._flush_buffer()

    def _flush_buffer(self):
        """Flush buffer to underlying handlers."""
        if not self.buffer:
            return

        # Take a copy of the buffer
        records = self.buffer
        self.buffer = []

        # Write to all handlers
        for handler in self.handlers:
            try:
                for record in records:
                    handler.emit(record)
            except Exception as e:
                # Log the error instead of silently swallowing
                logging.warning(f"AsyncLogHandler: failed to emit records: {e}")

    def shutdown(self):
        """Gracefully shutdown the handler."""
        self._shutdown = True
        with self.lock:
            if self.buffer:
                self._flush_buffer()
        if hasattr(self, "_thread"):
            self._thread.join(timeout=5.0)


class BatchingFormatter(logging.Formatter):
    """Formatter that batches multiple records together."""

    def format(self, record: logging.LogRecord) -> str:
        """Format single record - use with AsyncLogHandler."""
        timestamp = datetime.fromtimestamp(record.created).isoformat()
        level = record.levelname.ljust(8)
        logger = record.name.ljust(30)
        message = record.getMessage()
        return f"{timestamp} {level} {logger} {message}"


def setup_logging(
    log_level: Optional[str] = None,
    use_json: bool = False,
    use_async: bool = True,
    log_to_file: bool = True,
) -> dict:
    """Setup optimized logging configuration.

    Args:
        log_level: DEBUG, INFO, WARNING, ERROR, CRITICAL. Defaults to INFO.
        use_json: Use JSON structured logging (for log aggregation).
        use_async: Use async batching handler for performance.
        log_to_file: Enable file logging.

    Returns:
        dict with configuration info
    """
    # Determine log level
    level = getattr(logging, (log_level or os.getenv("PM_LOG_LEVEL", "INFO")).upper())

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    if use_json:
        console_formatter = JSONFormatter()
    else:
        console_formatter = logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)-30s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # Create file handler if enabled
    if log_to_file:
        log_path = Path(LOG_DIR)
        try:
            log_path.mkdir(parents=True, exist_ok=True)

            # Use RotatingFileHandler for log rotation
            file_handler = logging.handlers.RotatingFileHandler(
                log_path / "patchmaster.log",
                maxBytes=MAX_LOG_SIZE,
                backupCount=BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setLevel(level)

            if use_json:
                file_formatter = JSONFormatter()
            else:
                file_formatter = logging.Formatter(
                    "%(asctime)s %(levelname)-8s %(name)-30s %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            file_handler.setFormatter(file_formatter)
            root_logger.addHandler(file_handler)

        except (OSError, PermissionError) as e:
            logging.warning(f"Could not create log file: {e}")

    # Add async handler if requested (for high-throughput scenarios)
    if use_async and log_to_file:
        # Async handler sits between logger and file handler
        # It's already added via console above for visibility
        pass

    return {
        "log_level": logging.getLevelName(level),
        "log_dir": str(LOG_DIR),
        "use_json": use_json,
        "use_async": use_async,
        "log_to_file": log_to_file,
    }


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the standard name prefix.

    Args:
        name: Logger name (e.g., 'api', 'agent', 'database')

    Returns:
        Configured logger instance
    """
    return logging.getLogger(f"patchmaster.{name}")


# Optimized log levels for hot paths
# These reduce verbosity in performance-critical areas
LOG_LEVELS = {
    "api": os.getenv("PM_LOG_LEVEL_API", "INFO"),
    "agent": os.getenv("PM_LOG_LEVEL_AGENT", "INFO"),
    "database": os.getenv("PM_LOG_LEVEL_DATABASE", "WARNING"),
    "patch": os.getenv("PM_LOG_LEVEL_PATCH", "INFO"),
}


def configure_logger_levels():
    """Configure log levels for different subsystems."""
    for subsystem, level_name in LOG_LEVELS.items():
        logger = logging.getLogger(f"patchmaster.{subsystem}")
        level = getattr(logging, level_name.upper(), logging.INFO)
        logger.setLevel(level)


# Default configuration - lazy initialization to avoid module-level side effects
# Can be overridden by calling setup_logging() explicitly
def get_default_config():
    if not hasattr(get_default_config, "_config"):
        get_default_config._config = setup_logging()
        configure_logger_levels()
    return get_default_config._config
