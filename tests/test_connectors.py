import sqlite3
import pytest
from sqlalchemy import URL
from connectors.sql_db import SQLDatabaseConnector


def test_sqlite_schema_and_query(tmp_path):
    path = tmp_path / "demo.sqlite"
    db = sqlite3.connect(path)
    db.execute("create table items (id integer, name text)")
    db.execute("insert into items values (1,'A')")
    db.commit()
    db.close()
    c = SQLDatabaseConnector(URL.create("sqlite", database=str(path)), "test")
    assert c.test_connection()[0]
    assert c.get_schema().tables[0].name == "items"
    assert c.run_query("select name from items", 10, 10).iloc[0, 0] == "A"
    c.close()


def test_sqlite_connection_failure(tmp_path):
    c = SQLDatabaseConnector.from_fields("SQLite", path=str(tmp_path / "missing.db"))
    ok, message = c.test_connection()
    assert not ok and message
    c.close()


def test_sqlite_connection_is_read_only(tmp_path):
    path = tmp_path / "locked.sqlite"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE facts (value INTEGER)")
    db.execute("INSERT INTO facts VALUES (7)")
    db.commit()
    db.close()
    c = SQLDatabaseConnector.from_fields("SQLite", path=str(path))
    with pytest.raises(Exception):
        c.run_query("DELETE FROM facts", 10, 5)
    assert c.run_query("SELECT value FROM facts", 10, 5).iloc[0, 0] == 7
    c.close()


def test_database_schema_never_samples_sensitive_values(tmp_path):
    path = tmp_path / "private.sqlite"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE people (email TEXT, department TEXT, order_status TEXT, is_active INTEGER)")
    db.execute("INSERT INTO people VALUES ('hidden@example.test', 'Finance', 'Cancelled', 1)")
    db.commit()
    db.close()
    c = SQLDatabaseConnector.from_fields("SQLite", path=str(path))
    schema = c.get_schema()
    columns = {column.name: column for column in schema.tables[0].columns}
    assert columns["email"].sample_values == []
    assert columns["department"].sample_values == ["Finance"]
    assert columns["order_status"].sample_values == ["Cancelled"]
    assert columns["is_active"].sample_values == ["1"]
    assert list(c.get_sample_rows("people").columns) == ["department", "order_status", "is_active"]
    c.close()


def test_schema_contains_all_low_cardinality_values_and_ranges(tmp_path):
    path = tmp_path / "metadata.sqlite"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE facts (category TEXT, amount INTEGER, order_date DATE)")
    db.executemany(
        "INSERT INTO facts VALUES (?, ?, ?)",
        [(f"Group {i:02}", i, f"2025-01-{i:02}") for i in range(1, 19)],
    )
    db.commit()
    db.close()
    connector = SQLDatabaseConnector.from_fields("SQLite", path=str(path))
    columns = {column.name: column for column in connector.get_schema().tables[0].columns}
    assert columns["category"].sample_values == ["Group 01", "Group 02", "Group 03"]
    assert not columns["category"].values_complete
    assert columns["amount"].value_range == ("1", "18")
    assert columns["order_date"].value_range == ("2025-01-01", "2025-01-18")
    cached = connector.get_schema()
    assert cached is connector.get_schema()
    connector.refresh_schema()
    assert connector.get_schema() is not cached
    connector.close()


def test_low_cardinality_schema_keeps_every_distinct_value(tmp_path):
    path = tmp_path / "categories.sqlite"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE facts (category TEXT)")
    db.executemany("INSERT INTO facts VALUES (?)", [("West",), ("East",), ("West",)])
    db.commit()
    db.close()
    connector = SQLDatabaseConnector.from_fields("SQLite", path=str(path))
    column = connector.get_schema().tables[0].columns[0]
    assert column.sample_values == ["East", "West"]
    assert column.values_complete
    connector.close()


def test_url_create_preserves_special_password_characters():
    password = "p@ss:/?#word"
    c = SQLDatabaseConnector.from_fields(
        "MySQL",
        host="db.example.test",
        database="analytics",
        username="analyst",
        password=password,
    )
    assert c.engine.url.password == password
    assert "p@ss:/?#word" not in str(c.engine.url)
    c.close()


def test_fabric_odbc_connection_string_is_wrapped_for_sqlalchemy():
    raw = (
        "Driver={ODBC Driver 18 for SQL Server};"
        "Server=tcp:sample.datawarehouse.fabric.microsoft.com,1433;"
        "Database=SampleWarehouse;"
        "UID=app-id;PWD=placeholder;"
        "Authentication=ActiveDirectoryServicePrincipal;"
        "Encrypt=yes;TrustServerCertificate=no"
    )
    c = SQLDatabaseConnector.from_fields("SQL Server", connection_string=raw)
    assert c.dialect == "mssql"
    assert c.engine.url.query["odbc_connect"] == raw
    c.close()


def test_fabric_native_connection_string_gets_default_odbc_driver():
    raw = (
        "Data Source=tcp:sample.datawarehouse.fabric.microsoft.com,1433;"
        "Initial Catalog=SampleWarehouse;"
        "Authentication=ActiveDirectoryInteractive;"
    )
    c = SQLDatabaseConnector.from_fields("SQL Server", connection_string=raw)
    wrapped = c.engine.url.query["odbc_connect"]
    assert wrapped.startswith("Driver={ODBC Driver 18 for SQL Server};")
    assert "Initial Catalog=SampleWarehouse" in wrapped
    c.close()


def test_sql_server_connector_has_bounded_odbc_login_timeout():
    url = URL.create("mssql+pyodbc", query={"odbc_connect": "Driver={ODBC Driver 18 for SQL Server};"})
    assert SQLDatabaseConnector._connect_args(url) == {"timeout": 10}
