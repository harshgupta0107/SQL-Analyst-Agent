"""Compact schema ranking and prompt serialization."""

from __future__ import annotations
import re
from connectors.base import SchemaInfo


def relevant_schema(schema: SchemaInfo, question: str, limit: int = 8) -> SchemaInfo:
    """Rank tables by lexical overlap with the question and include top candidates."""
    terms = set(re.findall(r"[a-z0-9_]+", question.lower()))
    ranked = sorted(
        schema.tables,
        key=lambda t: sum(
            x in terms for x in [t.name.lower(), *(c.name.lower() for c in t.columns)]
        )
        + sum(any(term in c.name.lower() for term in terms) for c in t.columns),
        reverse=True,
    )
    chosen = ranked[:limit]
    selected = {table.name for table in chosen}
    selected_lower = {name.lower() for name in selected}
    neighbor_names = {
        col.foreign_key.split(".", 1)[0]
        for table in chosen
        for col in table.columns
        if col.foreign_key and "." in col.foreign_key
    }
    for table in schema.tables:
        points_to_selected = any(
            col.foreign_key
            and col.foreign_key.split(".", 1)[0].lower() in selected_lower
            for col in table.columns
        )
        if points_to_selected:
            neighbor_names.add(table.name)
        if table.name in neighbor_names and table.name not in selected:
            chosen.append(table)
            selected.add(table.name)
    return SchemaInfo(chosen)


def format_schema(schema: SchemaInfo) -> str:
    """Build a compact textual schema description."""
    lines = []
    for table in schema.tables:
        lines.append(
            f"Table {table.name} (rows={table.row_count if table.row_count is not None else 'unknown'}):"
        )
        for col in table.columns:
            flags = (
                " PK"
                if col.primary_key
                else (f" FK->{col.foreign_key}" if col.foreign_key else "")
            )
            sample = ""
            if col.sample_values:
                label = "all distinct values" if col.values_complete else "sample values"
                sample = f" {label}={col.sample_values}"
            value_range = f" range={col.value_range}" if col.value_range else ""
            original = (
                f" business label={col.original_name!r}"
                if col.original_name and col.original_name != col.name
                else ""
            )
            lines.append(
                f"  {col.name}: {col.data_type}{flags}{original}{sample}{value_range}"
            )
    return "\n".join(lines)
