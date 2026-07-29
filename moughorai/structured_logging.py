"""Structured, correlation-aware logging for Atlas."""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
from datetime import datetime, timezone
from enum import Enum
import json
import logging
from pathlib import Path
import sys
from typing import Any, TextIO
from uuid import uuid4


class LogFormat(str, Enum):
    JSON = "json"
    TEXT = "text"


class LogLevel(str, Enum):
    OFF = "off"
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


_correlation_id: ContextVar[str | None] = ContextVar("atlas_correlation_id", default=None)
_SENSITIVE = frozenset({"authorization", "password", "secret", "token", "api_key", "apikey"})
_root_logger = logging.getLogger("moughorai")
_root_logger.addHandler(logging.NullHandler())
_root_logger.propagate = False


def current_correlation_id() -> str | None:
    return _correlation_id.get()


def set_correlation_id(value: str | None = None) -> str:
    normalized = (value or uuid4().hex).strip()
    if not normalized:
        raise ValueError("correlation id must not be empty")
    _correlation_id.set(normalized)
    return normalized


def get_logger(name: str) -> logging.Logger:
    normalized = name if name.startswith("moughorai") else f"moughorai.{name}"
    return logging.getLogger(normalized)


def configure_logging(
    *,
    level: LogLevel | str = LogLevel.INFO,
    output_format: LogFormat | str = LogFormat.JSON,
    stream: TextIO | None = None,
    path: Path | None = None,
    correlation_id: str | None = None,
) -> str | None:
    """Configure only Atlas loggers, leaving host application logging intact."""
    selected_level = LogLevel(level)
    selected_format = LogFormat(output_format)
    for handler in tuple(_root_logger.handlers):
        _root_logger.removeHandler(handler)
        if not isinstance(handler, logging.NullHandler):
            handler.close()
    if selected_level is LogLevel.OFF:
        _root_logger.addHandler(logging.NullHandler())
        _root_logger.setLevel(logging.CRITICAL + 1)
        _correlation_id.set(None)
        return None
    if path is not None:
        target = path.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.FileHandler(target, encoding="utf-8")
    else:
        handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(AtlasJsonFormatter() if selected_format is LogFormat.JSON else AtlasTextFormatter())
    _root_logger.addHandler(handler)
    _root_logger.setLevel(getattr(logging, selected_level.value.upper()))
    return set_correlation_id(correlation_id)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    *,
    correlation_id: str | None = None,
    **fields: Any,
) -> None:
    logger.log(
        level,
        event,
        extra={
            "atlas_event": event,
            "atlas_correlation_id": correlation_id,
            "atlas_fields": _normalize(fields),
        },
    )


class AtlasJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = getattr(record, "atlas_fields", {})
        correlation = getattr(record, "atlas_correlation_id", None) or current_correlation_id()
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": getattr(record, "atlas_event", record.getMessage()),
            "message": record.getMessage(),
            "correlation_id": correlation,
            "thread": record.threadName,
            "fields": fields,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class AtlasTextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        correlation = getattr(record, "atlas_correlation_id", None) or current_correlation_id() or "-"
        fields = json.dumps(getattr(record, "atlas_fields", {}), sort_keys=True, separators=(",", ":"))
        return (
            f"{record.levelname.lower()} correlation_id={correlation} "
            f"event={getattr(record, 'atlas_event', record.getMessage())} "
            f"logger={record.name} fields={fields}"
        )


def _normalize(value: Any, *, key: str | None = None) -> Any:
    if key is not None and key.lower().replace("-", "_") in _SENSITIVE:
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(item_key): _normalize(value[item_key], key=str(item_key))
            for item_key in sorted(value, key=str)
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        values = [_normalize(item) for item in value]
        return sorted(values, key=lambda item: json.dumps(item, sort_keys=True, default=str)) if isinstance(value, (set, frozenset)) else values
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
