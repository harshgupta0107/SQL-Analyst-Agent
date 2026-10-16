"""Result verification, constrained summaries, and chart selection."""

from __future__ import annotations
import json
import re
from decimal import Decimal, InvalidOperation
import pandas as pd
from numbers import Number
from .prompts import INSIGHT_PROMPT, INSIGHT_SYSTEM_PROMPT


def _display_value(value) -> str:
    """Format a returned scalar without changing its underlying meaning."""
    if isinstance(value, Number) and not isinstance(value, bool):
        number = float(value)
        if number.is_integer():
            return f"{int(number):,}"
        return f"{number:,.2f}".rstrip("0").rstrip(".")
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat(sep=" ")
    return str(value)


def chart_type(frame: pd.DataFrame) -> str | None:
    """Choose a sensible chart type from result shape and column types."""
    if len(frame) < 2 or len(frame.columns) < 2:
        return None
    numeric = [c for c in frame if pd.api.types.is_numeric_dtype(frame[c])]
    if not numeric:
        return None
    date_cols = [
        c
        for c in frame
        if pd.api.types.is_datetime64_any_dtype(frame[c])
        or "date" in c.lower()
        or "time" in c.lower()
    ]
    if date_cols:
        return "line"
    categorical = [
        c for c in frame if c not in numeric and frame[c].nunique(dropna=True) <= 30
    ]
    if categorical:
        return (
            "pie"
            if frame[categorical[0]].nunique() <= 6
            and len(frame) == frame[categorical[0]].nunique()
            else "bar"
        )
    return None


def summarize(
    question: str,
    frame: pd.DataFrame,
    llm=None,
    assumptions: list[str] | None = None,
) -> str:
    """Summarize results with the configured insight prompt and safe fallback."""
    if frame.empty:
        return "The query returned no rows. The selected filters may be narrow or there may be no data in that period."
    if llm is not None:
        generated = _model_summary(question, frame, assumptions or [], llm)
        if generated:
            return generated
    if len(frame) == 1 and len(frame.columns) == 1:
        value = frame.iloc[0, 0]
        if pd.isna(value):
            return "The query returned no value for this measure."
        return f"{frame.columns[0].replace('_', ' ').capitalize()}: {_display_value(value)}"
    if len(frame) == 1:
        values = [
            f"{column.replace('_', ' ')}: {_display_value(frame.iloc[0][column])}"
            for column in frame.columns[:3]
            if not pd.isna(frame.iloc[0][column])
        ]
        if values:
            return "The result is " + "; ".join(values) + "."
    numeric = [column for column in frame if pd.api.types.is_numeric_dtype(frame[column])]
    if numeric:
        measure = numeric[0]
        valid = frame[measure].dropna()
        if not valid.empty:
            row = frame.loc[valid.idxmax()]
            category = next((column for column in frame if column not in numeric), None)
            label = (
                f" for {category.replace('_', ' ')} {_display_value(row[category])}"
                if category and not pd.isna(row[category])
                else ""
            )
            return (
                f"Across {len(frame):,} result rows, the highest "
                f"{measure.replace('_', ' ')} is {_display_value(row[measure])}{label}. "
                "Review the table for the full breakdown."
            )
    if len(frame) and len(frame.columns) >= 2:
        return f"The result contains {len(frame):,} rows. Review the table for the full breakdown."
    return f"The query returned {len(frame):,} rows across {len(frame.columns)} columns. Review the table below for the detailed results."


def _model_summary(
    question: str, frame: pd.DataFrame, assumptions: list[str], llm
) -> str | None:
    """Ask the insight prompt to summarize bounded result rows and verify figures."""
    records = []
    for _, row in frame.head(20).iterrows():
        records.append(
            {
                str(column): (
                    value.isoformat()
                    if isinstance(value, (pd.Timestamp,))
                    else value.item()
                    if hasattr(value, "item")
                    else value
                )
                for column, value in row.items()
                if not pd.isna(value)
            }
        )
    partial = len(frame) > len(records)
    while records:
        result_payload = {
            "rows_returned": len(frame),
            "records": records,
            "partial_summary_context": partial,
        }
        results = json.dumps(result_payload, ensure_ascii=False, default=str)
        if len(results) <= 12_000:
            break
        records = records[: max(1, len(records) // 2)]
        partial = True
    try:
        answer = llm.generate(
            [
                {"role": "system", "content": INSIGHT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": INSIGHT_PROMPT.format(
                        question=question,
                        assumptions=json.dumps(assumptions, ensure_ascii=False),
                        results=results,
                    ),
                },
            ]
        ).strip()
    except Exception:
        return None
    if not answer or len(answer) > 1200 or not _figures_are_in_results(answer, result_payload):
        return None
    return answer


_FIGURE = re.compile(r"(?<![\w])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?")


def _figures_are_in_results(answer: str, payload: dict) -> bool:
    """Reject numeric claims that do not appear in the summary input data."""
    allowed: set[str] = set()
    values = [payload.get("rows_returned")]
    values.extend(
        value for row in payload.get("records", []) for value in row.values()
    )
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        for token in _FIGURE.findall(str(value)):
            canonical = _canonical_number(token)
            if canonical is not None:
                allowed.add(canonical)
    return all(
        (canonical := _canonical_number(token)) is not None and canonical in allowed
        for token in _FIGURE.findall(answer)
    )


def _canonical_number(value: str) -> str | None:
    """Normalize comma-separated numbers for result grounding checks."""
    try:
        return str(Decimal(value.replace(",", "").removesuffix("% ").removesuffix("%")))
    except (InvalidOperation, ValueError):
        return None
