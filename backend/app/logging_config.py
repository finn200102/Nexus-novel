import logging
import re
import sys
import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4
from contextvars import ContextVar

request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
user_id_var: ContextVar[Optional[int]] = ContextVar("user_id", default=None)
library_id_var: ContextVar[Optional[int]] = ContextVar("library_id", default=None)
novel_id_var: ContextVar[Optional[int]] = ContextVar("novel_id", default=None)


# Credentials that travel in the URL: Kobo device tokens and personal feed
# tokens in the path, one-time links (password reset and similar) in ?token=.
_SECRET_PATTERNS = (
    (re.compile(r"(/podcasts/)[^/?#\s]+"), r"\1***"),
    (re.compile(r"(/kobo/)[^/?#\s]+"), r"\1***"),
    (re.compile(r"(/feeds/)[^/?#\s]+?(\.atom)"), r"\1***\2"),
    (re.compile(r"(/feeds/)[^/?#\s.]+"), r"\1***"),
    (re.compile(r"([?&](?:token|access_token|code|state)=)[^&#\s]+", re.IGNORECASE), r"\1***"),
)


def redact_url(value: str) -> str:
    """Mask URL credentials before a path or URL reaches a log line."""
    for pattern, replacement in _SECRET_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


class AccessLogRedactionFilter(logging.Filter):
    """uvicorn's access log passes (client, method, path, version, status)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(redact_url(arg) if isinstance(arg, str) else arg for arg in record.args)
        return True


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = request_id_var.get()
        if request_id:
            log_data["request_id"] = request_id

        user_id = user_id_var.get()
        if user_id:
            log_data["user_id"] = user_id

        library_id = library_id_var.get()
        if library_id:
            log_data["library_id"] = library_id

        novel_id = novel_id_var.get()
        if novel_id:
            log_data["novel_id"] = novel_id

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        extra = getattr(record, "extra", None)
        if extra:
            log_data["extra"] = extra

        return json.dumps(log_data)


class ContextLogger:
    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def _build_context(self, **kwargs) -> dict:
        context = {}
        for key, value in kwargs.items():
            if value is not None:
                context[key] = value
        return context

    def debug(self, message: str, **kwargs):
        self._logger.debug(message, extra={"extra": self._build_context(**kwargs)})

    def info(self, message: str, **kwargs):
        self._logger.info(message, extra={"extra": self._build_context(**kwargs)})

    def warning(self, message: str, **kwargs):
        self._logger.warning(message, extra={"extra": self._build_context(**kwargs)})

    def error(self, message: str, **kwargs):
        self._logger.error(message, extra={"extra": self._build_context(**kwargs)})

    def critical(self, message: str, **kwargs):
        self._logger.critical(message, extra={"extra": self._build_context(**kwargs)})


def get_logger(name: str) -> ContextLogger:
    return ContextLogger(logging.getLogger(name))


def setup_logging(level: str = "INFO") -> logging.Logger:
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if root_logger.handlers:
        root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)

    json_formatter = StructuredFormatter()
    console_handler.setFormatter(json_formatter)

    root_logger.addHandler(console_handler)

    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("fastapi").setLevel(logging.INFO)
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, AccessLogRedactionFilter) for f in access.filters):
        access.addFilter(AccessLogRedactionFilter())
    # httpx logs every outgoing URL at INFO; webhook and Apprise URLs carry secrets.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    return root_logger


def set_request_id(request_id: Optional[str] = None) -> str:
    if request_id is None:
        request_id = str(uuid4())[:8]
    request_id_var.set(request_id)
    return request_id


def get_request_id() -> Optional[str]:
    return request_id_var.get()


def set_user_context(
    user_id: Optional[int] = None,
    library_id: Optional[int] = None,
    novel_id: Optional[int] = None,
):
    if user_id is not None:
        user_id_var.set(user_id)
    if library_id is not None:
        library_id_var.set(library_id)
    if novel_id is not None:
        novel_id_var.set(novel_id)


def clear_user_context():
    user_id_var.set(None)
    library_id_var.set(None)
    novel_id_var.set(None)
