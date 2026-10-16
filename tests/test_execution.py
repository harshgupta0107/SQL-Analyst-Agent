"""Execution row-cap and truncation checks against DuckDB."""

import pandas as pd

from agent.executor import execute_query
from connectors.base import ColumnInfo, SchemaInfo, TableInfo
from connectors.file_loader import FileDataConnector


def test_executor_caps_returned_rows_and_marks_truncation():
    connector = FileDataConnector()
    data = pd.DataFrame({"id": range(1205)})
    connector.connection.register("upload", data)
    connector.connection.execute('CREATE TABLE "items" AS SELECT * FROM upload')
    connector.connection.unregister("upload")
    connector._tables.append("items")
    schema = SchemaInfo([TableInfo("items", [ColumnInfo("id", "BIGINT")], 1205)])
    result = execute_query(connector, "SELECT id FROM items", schema, 1000, 5)
    assert len(result.frame) == 1000
    assert result.truncated is True
    assert "LIMIT 1001" in result.sql.upper()
    connector.close()
