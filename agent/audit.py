"""Credential-aware audit log redaction helpers."""

from __future__ import annotations

import re

_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization)\b\s*[:=]\s*([^\s,;]+)"
)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_LONG_DIGITS = re.compile(r"(?<!\d)(?:\d[ -]?){9,}(?!\d)")
_API_TOKEN = re.compile(r"\b(?:sk|gsk|AIza)[A-Za-z0-9_-]{16,}\b")
_SQL_STRING = re.compile(r"'(?:''|[^'])*'")


def redact_text(value: str) -> str:
    """Remove common credentials and direct identifiers from audit text."""
    value = _ASSIGNMENT.sub(r"\1=[REDACTED]", value)
    value = _EMAIL.sub("[EMAIL]", value)
    value = _LONG_DIGITS.sub("[NUMBER]", value)
    return _API_TOKEN.sub("[TOKEN]", value)


def redact_sql(sql: str) -> str:
    """Mask SQL string literals before writing the query to logs."""
    return redact_text(_SQL_STRING.sub("'[REDACTED]'", sql))
