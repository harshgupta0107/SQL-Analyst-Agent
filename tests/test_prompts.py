"""Prompt template and dialect coverage checks."""

from string import Formatter

from agent.prompts import (
    DIALECT_RULES,
    INSIGHT_PROMPT,
    INSIGHT_SYSTEM_PROMPT,
    PROMPT_VERSION,
    SQL_USER_PROMPT,
    SYSTEM_PROMPT,
    dialect_rules_for,
)


def placeholders(template):
    return {field for _, field, _, _ in Formatter().parse(template) if field}


def test_every_prompt_template_formats_with_expected_values():
    system = SYSTEM_PROMPT.format(today="2026-10-16")
    sql = SQL_USER_PROMPT.format(
        dialect="mssql",
        dialect_rules=dialect_rules_for("mssql"),
        schema="Table sales",
        context="",
        question="sales total",
        error="",
    )
    insight = INSIGHT_PROMPT.format(
        question="sales total", assumptions=[], results='{"total": 5}'
    )

    assert "2026-10-16" in system
    assert "T-SQL" in sql
    assert "sales total" in insight
    assert INSIGHT_SYSTEM_PROMPT
    assert PROMPT_VERSION


def test_prompt_placeholders_match_call_sites():
    assert placeholders(SYSTEM_PROMPT) == {"today"}
    assert placeholders(SQL_USER_PROMPT) == {
        "dialect",
        "dialect_rules",
        "schema",
        "context",
        "question",
        "error",
    }
    assert placeholders(INSIGHT_PROMPT) == {"question", "assumptions", "results"}


def test_dialect_rules_exist_for_each_supported_dialect():
    for dialect in ("mssql", "postgres", "mysql", "sqlite", "duckdb"):
        assert dialect_rules_for(dialect) == DIALECT_RULES[dialect]
    assert "AVG" in dialect_rules_for("mssql")
