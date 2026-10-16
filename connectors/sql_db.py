"""Read-only SQLAlchemy connector for relational databases."""

from __future__ import annotations
from pathlib import Path
import time
import pandas as pd
from sqlalchemy import URL, create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from .base import (
    ColumnInfo,
    SchemaInfo,
    TableInfo,
    SENSITIVE_COLUMN_TOKENS,
    is_status_column,
)


class SQLDatabaseConnector:
    """Database connector that holds credentials only in its engine/session memory."""

    def __init__(self, url: URL | str, name: str, dialect: str | None = None):
        self.name = name
        self.engine: Engine = create_engine(
            url, pool_pre_ping=True, connect_args=self._connect_args(url)
        )
        self.dialect = dialect or self.engine.dialect.name
        self._schema_cache: SchemaInfo | None = None

    @staticmethod
    def _connect_args(url: URL | str) -> dict:
        if isinstance(url, URL) and url.drivername.startswith("sqlite"):
            return {"timeout": 10}
        if isinstance(url, str) and url.startswith("sqlite"):
            return {"timeout": 10}
        if isinstance(url, URL) and url.drivername.startswith("mssql+pyodbc"):
            return {"timeout": 10}
        return (
            {"connect_timeout": 10}
            if isinstance(url, URL)
            and url.drivername.startswith(("postgresql", "mysql"))
            else {}
        )

    @classmethod
    def from_fields(
        cls,
        kind: str,
        *,
        host: str = "",
        port: int | None = None,
        database: str = "",
        username: str = "",
        password: str = "",
        path: str = "",
        connection_string: str = "",
    ) -> "SQLDatabaseConnector":
        """Build a connector using safely escaped URL fields or an advanced URL."""
        kinds = {
            "PostgreSQL": ("postgresql+psycopg2", 5432),
            "MySQL": ("mysql+pymysql", 3306),
            "SQL Server": ("mssql+pyodbc", 1433),
        }
        if connection_string.strip():
            advanced = connection_string.strip()
            if "://" in advanced:
                url: URL | str = advanced
                dialect = advanced.split(":", 1)[0].split("+", 1)[0]
            elif _looks_like_odbc_connection_string(advanced):
                # Accept Fabric's native endpoint string even when it omits Driver=.
                if not any(
                    key in advanced.lower()
                    for key in ("driver=", "driver =")
                ):
                    advanced = "Driver={ODBC Driver 18 for SQL Server};" + advanced
                url = URL.create(
                    "mssql+pyodbc", query={"odbc_connect": advanced}
                )
                dialect = "mssql"
            else:
                raise ValueError(
                    "Enter a SQLAlchemy URL or a complete ODBC connection string."
                )
        elif kind == "SQLite":
            if not path.strip():
                raise ValueError("Choose an existing SQLite database file.")
            url = URL.create(
                "sqlite",
                database=f"file:{Path(path).expanduser().as_posix()}",
                query={"mode": "ro", "uri": "true"},
            )
            dialect = "sqlite"
        elif kind in kinds:
            if not host.strip() or not database.strip():
                raise ValueError("Enter the database host and database name.")
            driver, default_port = kinds[kind]
            query = (
                {
                    "driver": "ODBC Driver 18 for SQL Server",
                    "TrustServerCertificate": "yes",
                    "ApplicationIntent": "ReadOnly",
                }
                if kind == "SQL Server"
                else {}
            )
            url = URL.create(
                driver,
                username=username or None,
                password=password or None,
                host=host,
                port=port or default_port,
                database=database,
                query=query,
            )
            dialect = {
                "PostgreSQL": "postgres",
                "MySQL": "mysql",
                "SQL Server": "mssql",
            }[kind]
        else:
            raise ValueError("Choose a supported database type.")
        return cls(url, kind, dialect)

    def test_connection(self) -> tuple[bool, str]:
        """Check connectivity and return a friendly diagnostic."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True, "Connection successful."
        except Exception as exc:
            msg = str(exc).lower()
            if "login failed" in msg or "authentication" in msg or "password" in msg:
                return False, "Authentication failed. Check the username and password."
            if (
                "unknown database" in msg
                or "database" in msg
                and "does not exist" in msg
            ):
                return (
                    False,
                    "The database name was not found. Check the database field.",
                )
            if (
                "could not translate" in msg
                or "connection refused" in msg
                or "timeout" in msg
            ):
                return (
                    False,
                    "The database host could not be reached. Check the host, port, and firewall.",
                )
            if "no such file" in msg:
                return (
                    False,
                    "The SQLite database file was not found. Check the file path.",
                )
            if "no module named" in msg or "driver" in msg or "data source name" in msg:
                return (
                    False,
                    "A database driver is missing. Install the driver listed in requirements.txt.",
                )
            return (
                False,
                "Connection failed. Check the database name, credentials, host, port, and driver.",
            )

    def get_schema(self) -> SchemaInfo:
        """Inspect tables and columns without retrieving full table data."""
        if self._schema_cache is not None:
            return self._schema_cache
        inspector = inspect(self.engine)
        tables: list[TableInfo] = []
        with self.engine.connect() as conn:
            for name in inspector.get_table_names():
                pk = set(
                    inspector.get_pk_constraint(name).get("constrained_columns") or []
                )
                fks = {
                    c: f"{fk.get('referred_table')}.{(fk.get('referred_columns') or [''])[0]}"
                    for fk in inspector.get_foreign_keys(name)
                    for c in (fk.get("constrained_columns") or [])
                }
                cols = []
                for c in inspector.get_columns(name):
                    samples = []
                    values_complete = False
                    value_range = None
                    sensitive = any(
                        token in c["name"].lower() for token in SENSITIVE_COLUMN_TOKENS
                    )
                    status_column = is_status_column(c["name"], str(c["type"]))
                    is_text = any(
                        t in str(c["type"]).lower() for t in ("char", "text", "enum")
                    )
                    if not sensitive and (status_column or is_text):
                        quoted_table = self.engine.dialect.identifier_preparer.quote(
                            name
                        )
                        quoted_column = self.engine.dialect.identifier_preparer.quote(
                            c["name"]
                        )
                        sample_sql = (
                            f"SELECT DISTINCT TOP (16) {quoted_column} FROM {quoted_table} WHERE {quoted_column} IS NOT NULL ORDER BY {quoted_column}"
                            if self.dialect == "mssql"
                            else f"SELECT DISTINCT {quoted_column} FROM {quoted_table} WHERE {quoted_column} IS NOT NULL ORDER BY {quoted_column} LIMIT 16"
                        )
                        try:
                            values = [row[0] for row in conn.execute(text(sample_sql)).fetchall()]
                            values_complete = len(values) <= 15
                            samples = [str(value)[:80] for value in (values if values_complete else values[:3])]
                        except SQLAlchemyError:
                            samples = []
                    dtype = str(c["type"]).lower()
                    is_numeric_or_temporal = any(
                        token in dtype
                        for token in (
                            "int", "decimal", "numeric", "real", "float", "double",
                            "money", "number", "date", "time",
                        )
                    )
                    if not sensitive and is_numeric_or_temporal:
                        quoted_table = self.engine.dialect.identifier_preparer.quote(name)
                        quoted_column = self.engine.dialect.identifier_preparer.quote(c["name"])
                        try:
                            bounds = conn.execute(
                                text(f"SELECT MIN({quoted_column}), MAX({quoted_column}) FROM {quoted_table}")
                            ).one()
                            if bounds[0] is not None and bounds[1] is not None:
                                value_range = (str(bounds[0]), str(bounds[1]))
                        except SQLAlchemyError:
                            value_range = None
                    cols.append(
                        ColumnInfo(
                            name=c["name"],
                            data_type=str(c["type"]),
                            nullable=c.get("nullable", True),
                            primary_key=c["name"] in pk,
                            foreign_key=fks.get(c["name"]),
                            sample_values=samples,
                            values_complete=values_complete,
                            value_range=value_range,
                        )
                    )
                try:
                    count = int(
                        conn.execute(
                            text(
                                f"SELECT COUNT(*) FROM {self.engine.dialect.identifier_preparer.quote(name)}"
                            )
                        ).scalar_one()
                    )
                except SQLAlchemyError:
                    count = None
                tables.append(TableInfo(name, cols, count))
        self._schema_cache = SchemaInfo(tables)
        return self._schema_cache

    def refresh_schema(self) -> SchemaInfo:
        """Invalidate and rebuild cached schema metadata."""
        self._schema_cache = None
        return self.get_schema()

    def get_sample_rows(self, table: str, n: int = 3) -> pd.DataFrame:
        """Return a small sample for schema context."""
        quoted = self.engine.dialect.identifier_preparer.quote(table)
        schema = self.get_schema()
        allowed = [
            column.name
            for item in schema.tables
            if item.name.lower() == table.lower()
            for column in item.columns
            if not any(
                token in column.name.lower() for token in SENSITIVE_COLUMN_TOKENS
            )
        ]
        if not allowed:
            return pd.DataFrame()
        quoted_columns = ", ".join(
            self.engine.dialect.identifier_preparer.quote(column) for column in allowed
        )
        return (
            pd.read_sql_query(
                text(f"SELECT {quoted_columns} FROM {quoted} LIMIT :n"),
                self.engine,
                params={"n": n},
            )
            if self.dialect != "mssql"
            else pd.read_sql_query(
                text(f"SELECT TOP ({int(n)}) {quoted_columns} FROM {quoted}"),
                self.engine,
            )
        )

    def run_query(self, sql: str, max_rows: int, timeout: int) -> pd.DataFrame:
        """Run SQL within a read-only transaction and enforce an outer row cap."""
        with self.engine.connect() as raw:
            conn = (
                raw.execution_options(isolation_level="AUTOCOMMIT")
                if self.dialect == "sqlite"
                else raw
            )
            if self.dialect in {"postgres", "postgresql"}:
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                conn.exec_driver_sql(
                    "SET LOCAL statement_timeout = %d" % (int(timeout) * 1000)
                )
            elif self.dialect == "mysql":
                conn.exec_driver_sql("SET SESSION TRANSACTION READ ONLY")
                try:
                    conn.exec_driver_sql(
                        "SET SESSION MAX_EXECUTION_TIME = %d" % (int(timeout) * 1000)
                    )
                except SQLAlchemyError:
                    conn.exec_driver_sql(
                        "SET SESSION max_statement_time = %d" % int(timeout)
                    )
            if self.dialect == "sqlite":
                conn.exec_driver_sql("PRAGMA query_only = ON")
                dbapi_connection = conn.connection.driver_connection
                deadline = time.monotonic() + int(timeout)
                dbapi_connection.set_progress_handler(
                    lambda: 1 if time.monotonic() >= deadline else 0, 1000
                )
            if self.dialect == "mssql":
                conn.connection.driver_connection.timeout = int(timeout)
            try:
                result = conn.execute(text(sql))
                rows = result.fetchmany(max_rows + 1)
                frame = pd.DataFrame(rows[:max_rows], columns=result.keys())
                frame.attrs["truncated"] = len(rows) > max_rows
                return frame
            finally:
                if self.dialect == "sqlite":
                    dbapi_connection.set_progress_handler(None, 0)

    def close(self) -> None:
        """Dispose pooled database connections."""
        self.engine.dispose()


def _looks_like_odbc_connection_string(value: str) -> bool:
    """Recognize common native ODBC and Fabric endpoint string formats."""
    lowered = value.lower()
    has_server = any(
        marker in lowered for marker in ("server=", "data source=", "address=")
    )
    has_database = any(
        marker in lowered for marker in ("database=", "initial catalog=")
    )
    return has_server and has_database
