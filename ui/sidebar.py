"""Sidebar controls for database and file sources."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol, Sequence
from uuid import uuid4

import streamlit as st

from connectors.file_loader import FileDataConnector
from connectors.base import BaseConnector
from connectors.sql_db import SQLDatabaseConnector
from config import Settings


class UploadedFileLike(Protocol):
    """Minimal Streamlit upload interface used by staged loaders."""

    name: str

    def getvalue(self) -> bytes:
        """Return uploaded bytes held in session memory."""


def _fabric_odbc_connection_string(
    server: str,
    database: str,
    auth_mode: str,
    client_id: str = "",
    client_secret: str = "",
    tenant_id: str = "",
) -> str:
    """Build an ODBC string for the supported Fabric Microsoft Entra modes."""
    def odbc_value(value: str) -> str:
        return "{" + value.replace("}", "}}") + "}"

    if auth_mode == "Service principal":
        authentication = (
            "Authentication=ActiveDirectoryServicePrincipal;"
            f"UID={odbc_value(client_id)};PWD={odbc_value(client_secret)};"
            + (f"Authority Id={odbc_value(tenant_id)};" if tenant_id else "")
        )
    else:
        authentication = "Authentication=ActiveDirectoryInteractive;"
    return (
        "Driver={ODBC Driver 18 for SQL Server};"
        f"Server=tcp:{server.strip()},1433;"
        f"Database={odbc_value(database)};"
        + authentication
        + "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=10;"
    )


def _store_source(label: str, connector: BaseConnector) -> None:
    """Register a connector without replacing another same-type connection."""
    sources = st.session_state.sources
    unique = label
    suffix = 2
    while unique in sources:
        unique = f"{label} {suffix}"
        suffix += 1
    sources[unique] = connector
    st.session_state.source_cache_ids[unique] = uuid4().hex
    st.session_state.schema_revisions[unique] = 0
    st.session_state.active_source = unique
    st.session_state.active_source_picker = unique


def _remove_active_source() -> None:
    """Close the selected connection before the next app rerun."""
    selected = st.session_state.get("active_source_picker")
    connector = st.session_state.sources.pop(selected, None)
    if connector:
        connector.close()
    st.session_state.source_cache_ids.pop(selected, None)
    st.session_state.schema_revisions.pop(selected, None)
    next_source = next(iter(st.session_state.sources), None)
    st.session_state.active_source = next_source
    st.session_state.active_source_picker = next_source


def _load_uploads(
    uploads: Sequence[UploadedFileLike],
    connector: FileDataConnector,
    settings: Settings,
    replace: bool = False,
) -> None:
    """Load a batch only after preflighting all replacement conflicts."""
    staged = _stage_uploads(uploads, settings)
    conflicts = _replacement_conflicts(staged, connector)
    if conflicts and not replace:
        st.session_state.pending_file_replacements = conflicts
        st.session_state.confirm_replace_tables = False
        st.rerun()
    previews = []
    for filename, data in staged:
        previews.extend(
            connector.load_file(filename, data, settings.max_upload_mb, replace=replace)
        )
    st.session_state.upload_previews = previews
    st.session_state.sources["Uploaded files"] = connector
    if "Uploaded files" not in st.session_state.source_cache_ids:
        st.session_state.source_cache_ids["Uploaded files"] = uuid4().hex
        st.session_state.schema_revisions["Uploaded files"] = 0
    st.session_state.schema_revisions["Uploaded files"] += 1
    st.session_state.active_source = "Uploaded files"
    st.session_state.active_source_picker = "Uploaded files"
    st.session_state.pending_file_replacements = []
    st.success(f"Loaded {len(previews)} table(s) into the file workspace.")


def _stage_uploads(
    uploads: Sequence[UploadedFileLike], settings: Settings
) -> list[tuple[str, bytes]]:
    """Read uploaded bytes once and apply the configured size limit."""
    staged = [(upload.name, upload.getvalue()) for upload in uploads]
    for filename, data in staged:
        if len(data) > settings.max_upload_mb * 1024 * 1024:
            raise ValueError(
                f"{filename} exceeds the {settings.max_upload_mb} MB upload limit."
            )
    return staged


def _replacement_conflicts(
    staged: Sequence[tuple[str, bytes]], connector: FileDataConnector
) -> list[str]:
    """Find existing or duplicated destination names in a staged batch."""
    destinations = [
        table
        for filename, data in staged
        for table in connector.target_table_names(filename, data)
    ]
    return sorted(
        {table for table in destinations if table in connector.table_names}
        | {table for table in set(destinations) if destinations.count(table) > 1}
    )


def render_sidebar(settings: Settings) -> None:
    """Render connection forms and source management."""
    st.sidebar.header("SQL Analyst")
    if "sources" not in st.session_state:
        st.session_state.sources = {}
    if "source_cache_ids" not in st.session_state:
        st.session_state.source_cache_ids = {}
    if "schema_revisions" not in st.session_state:
        st.session_state.schema_revisions = {}
    for label in st.session_state.sources:
        st.session_state.source_cache_ids.setdefault(label, uuid4().hex)
        st.session_state.schema_revisions.setdefault(label, 0)

    if st.sidebar.button("New chat / Clear conversation", use_container_width=True):
        st.session_state.history = []
        if "agent" in st.session_state:
            st.session_state.agent.memory.clear()
        st.rerun()

    st.sidebar.markdown("#### 1 · Connect a source")
    with st.sidebar.expander("Database connection", expanded=False):
        kind = st.selectbox(
            "Database type",
            ["SQLite", "PostgreSQL", "MySQL", "SQL Server", "Microsoft Fabric"],
            key="db_kind",
        )
        advanced = st.checkbox("Use a full connection string", key="advanced_db")
        connection_string = (
            st.text_input(
                "Connection string",
                type="password",
                key="db_connection_string",
                help=(
                    "Paste a SQLAlchemy URL or complete ODBC connection string. The value stays masked."
                ),
            )
            if advanced
            else ""
        )
        tenant_id = ""
        if not advanced and kind == "Microsoft Fabric":
            host = st.text_input(
                "Fabric SQL endpoint", key="fabric_host",
                help="Use the server hostname shown in Warehouse or Lakehouse SQL endpoint details.",
                placeholder="workspace.datawarehouse.fabric.microsoft.com",
            )
            database = st.text_input("Warehouse or lakehouse SQL database", key="fabric_database")
            auth_mode = st.selectbox(
                "Microsoft Entra sign-in",
                ["Interactive (opens Microsoft sign-in)", "Service principal"],
                key="fabric_auth_mode",
            )
            if auth_mode == "Service principal":
                tenant_id = st.text_input("Tenant ID", key="fabric_tenant")
                username = st.text_input("Application (client) ID", key="fabric_client_id")
                password = st.text_input("Client secret", type="password", key="fabric_client_secret")
            else:
                username = password = ""
            port = 1433
        elif not advanced and kind == "SQLite":
            path = st.text_input("Existing database file", key="sqlite_path")
        elif not advanced:
            host = st.text_input("Host", key="db_host")
            port = st.number_input(
                "Port",
                value={"PostgreSQL": 5432, "MySQL": 3306, "SQL Server": 1433}[kind],
                key="db_port",
            )
            database = st.text_input("Database", key="db_name")
            username = st.text_input("Username", key="db_user")
            password = st.text_input("Password", type="password", key="db_password")
        st.caption(
            "Use a database identity with read-only permissions. Interactive Fabric sign-in may open a Microsoft login window."
        )
        if st.button("Test connection", key="test_db", use_container_width=True):
            connector = None
            stage = "configuration"
            try:
                with st.spinner(
                    "Connecting to the database. Complete Microsoft sign-in if prompted..."
                ):
                    fabric_connection_string = ""
                    if not advanced and kind == "Microsoft Fabric":
                        fabric_connection_string = _fabric_odbc_connection_string(
                            host,
                            database,
                            auth_mode,
                            username,
                            password,
                            tenant_id,
                        )
                    connector = SQLDatabaseConnector.from_fields(
                        "SQL Server" if kind == "Microsoft Fabric" else kind,
                        path=path if not advanced and kind == "SQLite" else "",
                        host=host if not advanced and kind != "SQLite" else "",
                        port=int(port) if not advanced and kind != "SQLite" else None,
                        database=database if not advanced and kind != "SQLite" else "",
                        username=username if not advanced and kind != "SQLite" else "",
                        password=password if not advanced and kind != "SQLite" else "",
                        connection_string=connection_string or fabric_connection_string,
                    )
                    stage = "connection"
                    ok, message = connector.test_connection()
                    if ok:
                        stage = "schema inspection"
                        with st.spinner("Connected. Loading table and column names…"):
                            schema = connector.get_schema()
                        _store_source(kind, connector)
                        st.success(
                            f"Connected, {len(schema.tables)} tables, {schema.column_count} columns."
                        )
                    else:
                        connector.close()
                        st.error(message)
            except Exception as exc:
                logging.error(
                    "Database connection %s failed (error_type=%s).",
                    stage,
                    type(exc).__name__,
                )
                if connector:
                    connector.close()
                if isinstance(exc, ValueError):
                    st.error(str(exc))
                elif stage == "schema inspection":
                    st.error(
                        "The endpoint accepted the connection, but schema inspection failed. "
                        "Check the selected database name and that your Entra identity has permission to read the Fabric item."
                    )
                elif type(exc).__name__ in {"NoSuchModuleError", "ModuleNotFoundError"}:
                    st.error(
                        "The SQL Server Python or ODBC driver is unavailable. Install the project requirements and Microsoft ODBC Driver 18 or later."
                    )
                else:
                    st.error(
                        "Could not initialize this connection. Check the endpoint, database name, Microsoft Entra permissions, and installed ODBC Driver 18."
                    )

    with st.sidebar.expander("Upload files", expanded=False):
        uploads = st.file_uploader(
            "CSV, TSV, or Excel workbook",
            type=["csv", "tsv", "xlsx", "xls"],
            accept_multiple_files=True,
            key="data_uploads",
            help=f"Up to {settings.max_upload_mb} MB per file. Every Excel sheet is loaded.",
        )
        if "file_connector" not in st.session_state:
            st.session_state.file_connector = FileDataConnector()
        pending = st.session_state.get("pending_file_replacements", [])
        if pending:
            st.warning("These existing tables will be replaced: " + ", ".join(pending))
            confirm = st.checkbox(
                "I confirm replacing these tables", key="confirm_replace_tables"
            )
            if st.button(
                "Replace and load files",
                disabled=not confirm or not uploads,
                key="confirm_file_replace",
                use_container_width=True,
            ):
                try:
                    staged = _stage_uploads(uploads, settings)
                    current_conflicts = _replacement_conflicts(
                        staged, st.session_state.file_connector
                    )
                    if current_conflicts != pending:
                        st.session_state.pending_file_replacements = current_conflicts
                        st.session_state.confirm_replace_tables = False
                        st.rerun()
                    with st.spinner("Replacing tables and refreshing previews…"):
                        _load_uploads(
                            uploads,
                            st.session_state.file_connector,
                            settings,
                            replace=True,
                        )
                except Exception as exc:
                    st.error(str(exc))
        elif st.button(
            "Load files",
            disabled=not uploads,
            key="load_files",
            use_container_width=True,
        ):
            try:
                with st.spinner("Reading files and loading DuckDB tables…"):
                    _load_uploads(uploads, st.session_state.file_connector, settings)
            except Exception as exc:
                st.error(str(exc))

    st.sidebar.caption("Secondary · use the built-in demo dataset")
    if st.sidebar.button("Load sample data", key="load_sample", use_container_width=True):
        sample = FileDataConnector()
        sample_dir = Path(__file__).resolve().parents[1] / "sample_data"
        try:
            with st.spinner("Loading the demo dataset…"):
                for file in sample_dir.glob("*.csv"):
                    sample.load_file(
                        file.name, file.read_bytes(), settings.max_upload_mb
                    )
            _store_source("Sample data", sample)
            st.sidebar.success("Demo data is ready.")
        except Exception as exc:
            sample.close()
            st.sidebar.error(str(exc))

    st.sidebar.markdown("#### 2 · Active source")
    if st.session_state.sources:
        labels = list(st.session_state.sources)
        selected = st.sidebar.selectbox(
            "Switch active source",
            labels,
            index=labels.index(st.session_state.get("active_source", labels[0])),
            key="active_source_picker",
        )
        st.session_state.active_source = selected
        active_connector = st.session_state.sources.get(selected)
        with st.sidebar.container(border=True):
            st.markdown(f"**{selected}**")
            if active_connector:
                try:
                    active_schema = active_connector.get_schema()
                    st.success(
                        f"Connected · {len(active_schema.tables)} tables · {active_schema.column_count} columns"
                    )
                except Exception:
                    st.success("Connected")
            st.button(
                "Disconnect source",
                use_container_width=True,
                on_click=_remove_active_source,
            )

    st.sidebar.markdown("#### 3 · Settings")
    with st.sidebar.expander("Result formatting", expanded=False):
        st.selectbox("Appearance", ["Dark", "Light"], key="ui_theme")
        st.checkbox(
            "Indian number grouping (lakh/crore)",
            key="indian_number_grouping",
            help="Uses localized display while keeping values numeric and sortable; browser locale controls the exact grouping.",
        )
        st.selectbox("Currency symbol", ["None", "₹", "$", "€", "£"], key="currency_symbol")
