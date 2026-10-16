"""Testable SQL generation, validation, execution, and retry workflow."""

from __future__ import annotations
import json
import logging
import re
from datetime import date
from dataclasses import dataclass, field
from typing import Protocol, Sequence

import pandas as pd

from connectors.base import BaseConnector, SchemaInfo
from .executor import execute_query
from .audit import redact_sql, redact_text
from .insights import summarize, chart_type
from .memory import ConversationMemory
from .prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    SQL_USER_PROMPT,
    dialect_rules_for,
)
from .schema_context import relevant_schema, format_schema
from .verification import result_warnings

logger = logging.getLogger(__name__)


class ModelClient(Protocol):
    """Minimal provider interface required by the workflow."""

    provider: str

    def generate(self, messages: Sequence[dict[str, str]], json_mode: bool = False) -> str:
        """Generate a model response."""


@dataclass
class AgentResponse:
    """Structured response for the chat UI."""

    kind: str
    answer: str
    sql: str = ""
    frame: pd.DataFrame | None = None
    chart: str | None = None
    assumptions: list[str] | None = None
    truncated: bool = False
    error: str = ""
    suggestions: list[str] | None = None
    dialect: str = ""
    retry_count: int = 0
    warnings: list[str] = field(default_factory=list)


class SQLAnalystAgent:
    """Coordinate model calls and safe execution against one active connector."""

    def __init__(
        self,
        llm: ModelClient,
        max_rows: int = 1000,
        timeout: int = 30,
        memory: ConversationMemory | None = None,
    ) -> None:
        self.llm = llm
        self.max_rows = max_rows
        self.timeout = timeout
        self.memory = memory or ConversationMemory()

    def ask(self, question: str, connector: BaseConnector) -> AgentResponse:
        """Answer a question with at most three SQL attempts."""
        pending = self.memory.consume_pending_clarification()
        if pending:
            question = f"{question} (clarifying the earlier request: {pending})"
        schema = connector.get_schema()
        lowered = question.lower().strip()
        if lowered.rstrip("?!.") in {"hi", "hello", "hey", "help", "what can you do"}:
            return AgentResponse(
                "help",
                "I can answer questions about the active data source. Ask for a total, trend, comparison, ranking, or breakdown.",
            )
        if lowered.startswith(
            ("write a poem", "tell me a joke", "what is the weather", "draft an email")
        ):
            return AgentResponse(
                "out_of_scope",
                "I’m focused on answering questions about the active data source. Try asking for a total, trend, comparison, or ranking.",
            )
        if any(
            x in lowered
            for x in ("what tables", "show tables", "what columns", "describe schema")
        ):
            listing = "\n".join(
                f"{t.name}: {', '.join(c.name for c in t.columns)}"
                for t in schema.tables
            )
            return AgentResponse("schema", listing or "No tables are available.")
        clarification = self._clarification(question, schema)
        if clarification:
            self.memory.set_pending_clarification(question)
            return AgentResponse(
                "clarify", "Which measure did you mean?", suggestions=clarification
            )
        compact = relevant_schema(schema, question)
        schema_text = format_schema(compact)
        logger.info(
            "prompt_context version=%s dialect=%s schema=%s",
            PROMPT_VERSION,
            connector.dialect,
            redact_text(schema_text),
        )
        error = ""
        for attempt in range(3):
            messages = [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT.format(today=date.today().isoformat()),
                },
                {
                    "role": "user",
                    "content": SQL_USER_PROMPT.format(
                        dialect=connector.dialect,
                        dialect_rules=dialect_rules_for(connector.dialect),
                        schema=schema_text,
                        context=self.memory.context(),
                        question=question,
                        error=error,
                    ),
                },
            ]
            try:
                raw = self.llm.generate(messages, json_mode=True)
                payload = json.loads(raw)
                sql = payload.get("sql", "")
                result = execute_query(
                    connector, sql, schema, self.max_rows, self.timeout
                )
                assumptions = payload.get("assumptions", [])
                if not isinstance(assumptions, list):
                    assumptions = []
                assumptions = [str(item)[:500] for item in assumptions[:10]]
                answer = summarize(question, result.frame, self.llm, assumptions)
                self.memory.add(question, result.sql, answer)
                suggestions = (
                    [
                        "Show the date and value range in this data",
                        "Try this query without its filters",
                    ]
                    if result.frame.empty
                    else self._suggestions(schema, result.frame)
                )
                logger.info(
                    "query_success source=%s question=%s sql=%s runtime_seconds=%.3f rows=%d prompt_version=%s retries=%d",
                    connector.name,
                    redact_text(question),
                    redact_sql(result.sql),
                    result.runtime_seconds,
                    len(result.frame),
                    PROMPT_VERSION,
                    attempt,
                )
                return AgentResponse(
                    "data",
                    answer,
                    result.sql,
                    result.frame,
                    chart_type(result.frame),
                    assumptions,
                    result.truncated,
                    suggestions=suggestions,
                    dialect=connector.dialect,
                    retry_count=attempt,
                    warnings=[*result.warnings, *result_warnings(result.frame)],
                )
            except Exception as exc:
                error = str(exc) or type(exc).__name__
                logger.warning(
                    "query_attempt_failed source=%s attempt=%d error_type=%s",
                    connector.name,
                    attempt + 1,
                    type(exc).__name__,
                )
                if (
                    isinstance(exc, RuntimeError)
                    and "Both AI providers are unavailable" in error
                ):
                    return AgentResponse(
                        "provider_error",
                        "Both AI providers are temporarily unavailable. Retry your question in a moment.",
                        suggestions=[question],
                    )
                if attempt == 1 and hasattr(self.llm, "provider"):
                    self.llm.provider = "gemini"
        if "timeout" in error.lower() or "interrupt" in error.lower():
            return AgentResponse(
                "timeout",
                "The query took too long. Narrow the date range or add a filter, then try again.",
                error=error,
            )
        tables = ", ".join(table.name for table in schema.tables[:8])
        columns = ", ".join(
            f"{table.name}.{column.name}"
            for table in schema.tables[:4]
            for column in table.columns[:5]
        )
        return AgentResponse(
            "error",
            "I couldn't safely answer that query after three attempts. Rephrase it using available data.\n\n"
            + (f"Available tables: {tables}.\n\n" if tables else "")
            + (f"Some available columns: {columns}." if columns else ""),
            error=error,
        )

    @staticmethod
    def _clarification(question: str, schema: SchemaInfo) -> list[str] | None:
        """Ask one clarification for an underspecified measure request."""
        tokens = question.lower().strip().rstrip("?").split()
        measure_words = {"sales", "performance", "volume"}
        ignored = {"total", "overall", "the", "my", "show", "what", "is", "are"}
        if tokens and all(t in measure_words or t in ignored for t in tokens):
            pass
        else:
            period = r"\b(20\d{2}|today|yesterday|this month|last month|this quarter|last quarter|this year|last year|ytd|year to date|past \d+ months?)\b"
            comparison = re.search(
                r"\b(growth|increased|decreased|drop|change)\b", question.lower()
            )
            data_topic = re.search(
                r"\b(sales|revenue|profit|orders|customers|quantity|volume|performance)\b",
                question.lower(),
            )
            if comparison and data_topic and not re.search(period, question.lower()):
                return ["Month over month", "Quarter over quarter", "Year over year"]
            return None
        columns = {c.name.lower() for table in schema.tables for c in table.columns}
        has_revenue = (
            bool(columns & {"revenue", "sales_amount", "amount", "total"})
            or {"quantity", "unit_price"} <= columns
        )
        has_units = bool(columns & {"quantity", "units", "unit_count", "volume"})
        choices = []
        if has_revenue:
            choices.append("Show revenue")
        if has_units:
            choices.append("Show units sold")
        if len(choices) > 1:
            choices.append("Break sales down by category")
            return choices[:3]
        return None

    @staticmethod
    def _suggestions(schema: SchemaInfo, frame: pd.DataFrame) -> list[str]:
        """Build short schema-grounded follow-up suggestions."""
        columns = [c.name for table in schema.tables for c in table.columns]
        categorical = next(
            (
                c
                for c in columns
                if any(
                    k in c.lower() for k in ("region", "category", "segment", "status")
                )
            ),
            None,
        )
        temporal = next(
            (
                c
                for c in columns
                if any(k in c.lower() for k in ("date", "month", "year", "time"))
            ),
            None,
        )
        suggestions = []
        if categorical:
            suggestions.append(f"Break this down by {categorical.replace('_', ' ')}")
        if temporal:
            suggestions.append(
                f"Show the trend over time using {temporal.replace('_', ' ')}"
            )
        suggestions.append(
            "Show the top 5 results"
            if len(frame) > 1
            else "Compare this with the previous period"
        )
        return suggestions[:3]
