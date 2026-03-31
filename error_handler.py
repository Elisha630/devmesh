"""
DevMesh Error Handler with Structured Logging
----------------------------------------------
Comprehensive error handling with structured logging, error context, and dashboard integration.
"""

import logging
import traceback
from pathlib import Path
from typing import Dict, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum

import orjson


__all__ = [
    "ErrorSeverity",
    "ErrorContext",
    "StructuredErrorHandler",
    "get_error_handler",
]


class ErrorSeverity(Enum):
    """Error severity levels."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ErrorContext:
    """Context information for an error."""

    error_type: str
    message: str
    severity: ErrorSeverity
    source: str
    timestamp: str
    traceback_info: Optional[str] = None
    context_data: Dict[str, Any] = None
    handler_name: Optional[str] = None

    def __post_init__(self):
        if self.context_data is None:
            self.context_data = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = asdict(self)
        result["severity"] = self.severity.value
        return result


class StructuredErrorHandler:
    """Handles errors with structured logging and dashboard integration."""

    def __init__(self, log_dir: Path = None):
        self.log_dir = log_dir or Path(".devmesh")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.error_log_file = self.log_dir / "errors.jsonl"
        self.logger = logging.getLogger("devmesh.errors")
        self.callbacks = []

    def register_callback(self, callback: callable) -> None:
        """Register a callback to be called when errors occur."""
        self.callbacks.append(callback)

    def handle(
        self,
        error: Exception,
        source: str,
        handler_name: str = None,
        context_data: Dict[str, Any] = None,
        severity: ErrorSeverity = None,
    ) -> ErrorContext:
        """Handle an error with structured logging."""

        if severity is None:
            # Determine severity based on exception type
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                severity = ErrorSeverity.CRITICAL
            elif isinstance(error, (ValueError, TypeError, AttributeError)):
                severity = ErrorSeverity.WARNING
            else:
                severity = ErrorSeverity.ERROR

        error_context = ErrorContext(
            error_type=error.__class__.__name__,
            message=str(error),
            severity=severity,
            source=source,
            timestamp=datetime.now().isoformat(),
            traceback_info=traceback.format_exc(),
            context_data=context_data or {},
            handler_name=handler_name,
        )

        # Log to file
        self._log_to_file(error_context)

        # Log to logger
        self._log_to_logger(error_context)

        # Notify callbacks (e.g., dashboard)
        self._notify_callbacks(error_context)

        return error_context

    def _log_to_file(self, ctx: ErrorContext) -> None:
        """Log error to JSONL file."""
        try:
            with open(self.error_log_file, "ab") as f:
                f.write(orjson.dumps(ctx.to_dict()))
                f.write(b"\n")
        except Exception as e:
            self.logger.error(f"Failed to write error log: {e}")

    def _log_to_logger(self, ctx: ErrorContext) -> None:
        """Log error to Python logger."""
        message = f"[{ctx.source}] {ctx.error_type}: {ctx.message}"
        if ctx.handler_name:
            message = f"[{ctx.handler_name}] {message}"

        if ctx.severity == ErrorSeverity.CRITICAL:
            self.logger.critical(message, extra={"context": ctx.context_data})
        elif ctx.severity == ErrorSeverity.ERROR:
            self.logger.error(message, extra={"context": ctx.context_data})
        elif ctx.severity == ErrorSeverity.WARNING:
            self.logger.warning(message, extra={"context": ctx.context_data})
        else:
            self.logger.info(message, extra={"context": ctx.context_data})

    def _notify_callbacks(self, ctx: ErrorContext) -> None:
        """Notify registered callbacks about the error."""
        for callback in self.callbacks:
            try:
                callback(ctx)
            except Exception as e:
                self.logger.error(f"Error in callback: {e}")

    def get_recent_errors(self, limit: int = 100) -> list:
        """Get recent errors from the log file."""
        errors = []
        try:
            if self.error_log_file.exists():
                with open(self.error_log_file, "rb") as f:
                    for line in f.readlines()[-limit:]:
                        try:
                            errors.append(orjson.loads(line))
                        except Exception:
                            pass
        except Exception as e:
            self.logger.error(f"Failed to read error log: {e}")
        return errors


# Global error handler instance
_error_handler: Optional[StructuredErrorHandler] = None


def get_error_handler() -> StructuredErrorHandler:
    """Get the global error handler instance."""
    global _error_handler
    if _error_handler is None:
        _error_handler = StructuredErrorHandler()
    return _error_handler


def init_error_handler(log_dir: Path = None) -> StructuredErrorHandler:
    """Initialize the global error handler."""
    global _error_handler
    _error_handler = StructuredErrorHandler(log_dir)
    return _error_handler
