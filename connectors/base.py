"""Common connector protocol and schema models."""

from dataclasses import dataclass, field
from typing import Protocol
import pandas as pd

SENSITIVE_COLUMN_TOKENS = (
    "password",
    "passwd",
    "secret",
    "token",
    "ssn",
    "social_security",
    "credit_card",
    "card_number",
    "bank_account",
    "account_number",
    "email",
    "phone",
    "mobile",
    "address",
    "birth",
    "dob",
    "passport",
    "tax_id",
    "national_id",
)

STATUS_COLUMN_TOKENS = (
    "status",
    "state",
    "is_cancelled",
    "is_deleted",
    "is_active",
    "is_void",
)


def is_status_column(name: str, data_type: str = "") -> bool:
    """Identify business state fields that need sample values in model context."""
    lowered = name.lower()
    dtype = data_type.lower()
    return any(token in lowered for token in STATUS_COLUMN_TOKENS) or any(
        token in dtype for token in ("bool", "bit")
    )


@dataclass
class ColumnInfo:
    """Metadata for one table column."""

    name: str
    data_type: str
    nullable: bool = True
    primary_key: bool = False
    foreign_key: str | None = None
    sample_values: list[str] = field(default_factory=list)
    original_name: str | None = None
    values_complete: bool = False
    value_range: tuple[str, str] | None = None


@dataclass
class TableInfo:
    """Metadata for a table."""

    name: str
    columns: list[ColumnInfo]
    row_count: int | None = None


@dataclass
class SchemaInfo:
    """Schema metadata for a data source."""

    tables: list[TableInfo]

    @property
    def column_count(self) -> int:
        """Return total number of columns."""
        return sum(len(table.columns) for table in self.tables)


class BaseConnector(Protocol):
    """Interface consumed by the agent and UI."""

    name: str
    dialect: str

    def test_connection(self) -> tuple[bool, str]: ...
    def get_schema(self) -> SchemaInfo: ...
    def get_sample_rows(self, table: str, n: int = 3) -> pd.DataFrame: ...
    def run_query(self, sql: str, max_rows: int, timeout: int) -> pd.DataFrame: ...
    def close(self) -> None: ...
