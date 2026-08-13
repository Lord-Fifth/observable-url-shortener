"""Portable structured application logging for the resolver service."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from opentelemetry import trace

from resolver.correlation import get_correlation_id

SERVICE_NAME = "resolver"
LOGGER_NAME = "resolver.application"
_RESERVED_FIELDS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


class JsonFormatter(logging.Formatter):
    """Render one application record as stable, single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = (
            datetime.fromtimestamp(record.created, tz=UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        payload: dict[str, Any] = {
            "timestamp": timestamp,
            "severity": record.levelname,
            "service": SERVICE_NAME,
            "event": getattr(record, "event", "application_log"),
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", None) or get_correlation_id(),
        }
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            payload.update(
                {
                    "trace_id": f"{span_context.trace_id:032x}",
                    "span_id": f"{span_context.span_id:016x}",
                    "trace_sampled": span_context.trace_flags.sampled,
                }
            )
        for name, value in record.__dict__.items():
            if name not in _RESERVED_FIELDS and name not in payload and not name.startswith("_"):
                payload[name] = value
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=str)


def configure_logging() -> logging.Logger:
    """Configure one idempotent stdout handler owned by this application logger."""

    logger = logging.getLogger(LOGGER_NAME)
    if not any(getattr(handler, "phase2_json", False) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        handler.phase2_json = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


logger = configure_logging()


def log_event(
    level: int,
    event: str,
    message: str,
    *,
    correlation_id: str | None = None,
    **fields: object,
) -> None:
    """Emit a structured operational event without coupling callers to record internals."""

    extra = {"event": event, **fields}
    if correlation_id is not None:
        extra["correlation_id"] = correlation_id
    logger.log(level, message, extra=extra)
