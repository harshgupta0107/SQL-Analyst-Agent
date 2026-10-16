import pytest
from connectors.base import ColumnInfo, SchemaInfo, TableInfo
from agent.sql_validator import validate_sql, SQLValidationError, validation_warnings

SCHEMA = SchemaInfo(
    [
        TableInfo(
            "orders",
            [
                ColumnInfo("id", "INTEGER"),
                ColumnInfo("amount", "DOUBLE"),
                ColumnInfo("customer_id", "INTEGER"),
            ],
        ),
        TableInfo(
            "customers", [ColumnInfo("id", "INTEGER"), ColumnInfo("name", "TEXT")]
        ),
    ]
)


def test_warns_about_tsql_integer_average_and_division():
    schema = SchemaInfo([TableInfo("orders", [ColumnInfo("quantity", "INTEGER")])])
    warnings = validation_warnings(
        "SELECT AVG(quantity), quantity / 2 FROM orders", "mssql", schema
    )
    assert any("AVG over an integer" in warning for warning in warnings)
    assert any("Integer division" in warning for warning in warnings)


def test_warns_when_nullif_is_not_a_divisor_guard():
    warnings = validation_warnings(
        "SELECT NULLIF(amount, 0) - 1 FROM orders", "sqlite", SCHEMA
    )
    assert any("NULLIF should only guard" in warning for warning in warnings)


def test_warns_about_tsql_implicit_comparison_conversion():
    schema = SchemaInfo([TableInfo("orders", [ColumnInfo("amount", "INTEGER")])])
    warnings = validation_warnings(
        "SELECT amount FROM orders WHERE amount = '5'", "mssql", schema
    )
    assert any("implicitly convert" in warning for warning in warnings)


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders",
        "DROP TABLE orders",
        "UPDATE orders SET amount=0",
        "INSERT INTO orders VALUES (1,2,3)",
        "CREATE TABLE x(a int)",
        "SELECT 1; DROP TABLE orders",
        "SELECT * FROM orders --x",
        "SELECT read_csv('/tmp/a')",
        "SELECT amount INTO archived FROM orders",
        "SELECT * FROM orders FOR UPDATE",
        "SELECT nextval('dangerous_sequence')",
        "CALL dangerous_proc()",
        "PRAGMA table_info(orders)",
    ],
)
def test_rejects_forbidden(sql):
    with pytest.raises(SQLValidationError):
        validate_sql(sql, "duckdb", SCHEMA)


def test_accepts_cte_join_and_caps():
    sql = validate_sql(
        "WITH x AS (SELECT id FROM orders) SELECT c.name, SUM(o.amount) AS total FROM orders o JOIN customers c ON o.customer_id=c.id GROUP BY c.name",
        "duckdb",
        SCHEMA,
    )
    assert "LIMIT 1001" in sql.upper()


@pytest.mark.parametrize("sql", ["SELECT bad FROM orders", "SELECT * FROM missing"])
def test_rejects_unknown_schema(sql):
    with pytest.raises(SQLValidationError):
        validate_sql(sql, "duckdb", SCHEMA)


def test_canonicalizes_names_and_honors_requested_limit():
    sql = validate_sql("SELECT ID FROM ORDERS LIMIT 5000", "duckdb", SCHEMA, 100)
    assert "orders" in sql.lower()
    assert "id" in sql.lower()
    assert "LIMIT 101" in sql.upper()


def test_unqualified_ambiguous_join_column_is_rejected():
    with pytest.raises(SQLValidationError, match="Ambiguous column"):
        validate_sql(
            "SELECT id FROM orders o JOIN customers c ON o.customer_id=c.id",
            "duckdb",
            SCHEMA,
        )


def test_select_star_from_wide_schema_is_rejected():
    wide = SchemaInfo(
        [TableInfo("wide", [ColumnInfo(f"field_{i}", "TEXT") for i in range(13)])]
    )
    with pytest.raises(SQLValidationError, match="wide tables"):
        validate_sql("SELECT * FROM wide", "duckdb", wide)
