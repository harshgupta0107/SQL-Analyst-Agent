"""Lightweight result sanity checks that never modify returned query data."""

from __future__ import annotations

import pandas as pd


def result_warnings(frame: pd.DataFrame) -> list[str]:
    """Flag suspicious result shapes and values for display beside the result."""
    warnings: list[str] = []
    if frame.empty:
        return warnings

    all_null = [str(column) for column in frame if frame[column].isna().all()]
    if all_null:
        warnings.append(
            "These result columns contain only NULL values: "
            + ", ".join(all_null[:5])
            + ". Check the filters and source data."
        )

    nonnegative_tokens = (
        "quantity",
        "units_sold",
        "unit_count",
        "order_count",
        "customer_count",
        "row_count",
    )
    for column in frame:
        if any(token in str(column).lower() for token in nonnegative_tokens):
            values = pd.to_numeric(frame[column], errors="coerce")
            if (values.dropna() < 0).any():
                warnings.append(
                    f"{column} includes negative values; verify whether returns or adjustments are expected."
                )

    percentage_columns = [
        column
        for column in frame
        if any(
            token in str(column).lower()
            for token in ("percent_of_total", "percentage_of_total", "share_pct", "share_percent")
        )
        or str(column).strip().endswith("%")
    ]
    for column in percentage_columns:
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        if not len(values) or len(frame) > 50:
            continue
        total = float(values.sum())
        target = 1.0 if values.abs().max() <= 1.01 else 100.0
        tolerance = 0.03 if target == 1.0 else 3.0
        if abs(total - target) > tolerance:
            warnings.append(
                f"{column} does not add up to a complete share breakdown; check whether groups are missing."
            )
    return warnings
