"""Validated SQL execution and query metadata."""

from __future__ import annotations
import time
from dataclasses import dataclass
import pandas as pd
from connectors.base import BaseConnector, SchemaInfo
from .sql_validator import validate_sql, validation_warnings


@dataclass
class QueryResult:
    """Execution output and timing metadata."""

    sql: str
    frame: pd.DataFrame
    runtime_seconds: float
    truncated: bool
    warnings: list[str]


def execute_query(
    connector: BaseConnector, sql: str, schema: SchemaInfo, max_rows: int, timeout: int
) -> QueryResult:
    """Validate, execute, and measure a SQL query."""
    safe_sql = validate_sql(sql, connector.dialect, schema, max_rows)
    warnings = validation_warnings(safe_sql, connector.dialect, schema)
    start = time.perf_counter()
    frame = connector.run_query(safe_sql, max_rows, timeout)
    return QueryResult(
        safe_sql,
        frame,
        time.perf_counter() - start,
        bool(frame.attrs.get("truncated", False)),
        warnings,
    )
