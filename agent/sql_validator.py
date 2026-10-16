"""SQL parser and allowlist validation for read-only queries."""

from __future__ import annotations
import re
import sqlglot
from sqlglot import exp
from connectors.base import SENSITIVE_COLUMN_TOKENS, SchemaInfo

FORBIDDEN = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.Merge,
    exp.TruncateTable,
    exp.Into,
    exp.Lock,
)
UNSAFE_FUNCTIONS = {
    "PG_READ_FILE",
    "PG_READ_BINARY_FILE",
    "XP_CMDSHELL",
    "LOAD_FILE",
    "READ_CSV",
    "READ_CSV_AUTO",
    "READ_PARQUET",
    "READ_JSON",
    "INSTALL",
    "LOAD",
    "SYSTEM",
    "SET",
    "ATTACH",
    "DETACH",
    "COPY",
    "PG_SLEEP",
    "SLEEP",
    "NEXTVAL",
    "SETVAL",
    "PG_NOTIFY",
    "PG_ADVISORY_LOCK",
    "PG_TRY_ADVISORY_LOCK",
    "PG_TERMINATE_BACKEND",
    "PG_CANCEL_BACKEND",
    "PG_LS_DIR",
    "PG_STAT_FILE",
    "DBLINK",
    "OPENROWSET",
    "OPENQUERY",
    "GET_LOCK",
    "RELEASE_LOCK",
    "BENCHMARK",
    "HTTP_GET",
    "READ_TEXT",
    "READ_BLOB",
    "SET_CONFIG",
    "PG_LOGICAL_EMIT_MESSAGE",
    "PG_NOTIFY",
    "PG_RELOAD_CONF",
    "PG_ROTATE_LOGFILE",
    "PG_TERMINATE_BACKEND",
    "PG_CANCEL_BACKEND",
}


class SQLValidationError(ValueError):
    """Raised when a query violates syntax or safety rules."""


def validate_sql(
    sql: str, dialect: str, schema: SchemaInfo | None = None, max_rows: int = 1000
) -> str:
    """Validate a single read-only SELECT and return a capped query."""
    if not sql or not sql.strip():
        raise SQLValidationError("SQL is empty.")
    if re.search(r"(--|/\*|\*/|#)", sql):
        raise SQLValidationError("SQL comments are not allowed.")
    try:
        parsed = sqlglot.parse(sql, read=_dialect(dialect))
    except sqlglot.errors.ParseError as exc:
        raise SQLValidationError(
            "SQL syntax error: " + str(exc).splitlines()[0]
        ) from None
    if len(parsed) != 1 or parsed[0] is None:
        raise SQLValidationError("Only one SQL statement is allowed.")
    tree = parsed[0]
    if not isinstance(tree, (exp.Select, exp.Subquery)) and not (
        isinstance(tree, exp.Union)
        or isinstance(tree, exp.Intersect)
        or isinstance(tree, exp.Except)
    ):
        raise SQLValidationError("Only SELECT or WITH ... SELECT queries are allowed.")
    for node in tree.walk():
        if isinstance(node, FORBIDDEN):
            raise SQLValidationError(f"Forbidden SQL operation: {node.key.upper()}.")
        if isinstance(node, exp.Func):
            function_name = (
                node.name if isinstance(node, exp.Anonymous) else node.sql_name()
            ).upper()
            if function_name in UNSAFE_FUNCTIONS:
                raise SQLValidationError(
                    f"Unsafe function is not allowed: {function_name}."
                )
        if isinstance(node, exp.Command):
            raise SQLValidationError("Administrative SQL commands are not allowed.")
    if schema is not None:
        _check_schema(tree, schema)
    # Cap simple row-returning SELECTs in the AST. Outer cap also exists in executor.
    if isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        limit = tree.args.get("limit")
        if limit is None:
            tree = tree.limit(max_rows + 1)
        else:
            try:
                requested = int(limit.expression.this)
                if requested > max_rows:
                    tree.set(
                        "limit", exp.Limit(expression=exp.Literal.number(max_rows + 1))
                    )
            except (AttributeError, TypeError, ValueError):
                raise SQLValidationError(
                    "The LIMIT value must be a numeric literal."
                ) from None
    for column in tree.find_all(exp.Column):
        if any(token in column.name.lower() for token in SENSITIVE_COLUMN_TOKENS):
            raise SQLValidationError(
                f"Sensitive column access is blocked: {column.name}."
            )
    if schema is not None:
        for select in tree.find_all(exp.Select):
            for projection in select.expressions:
                wildcard = isinstance(projection, exp.Star) or (
                    isinstance(projection, exp.Column) and projection.is_star
                )
                if not wildcard:
                    continue
                visible_tables = [
                    table.name.lower()
                    for table in select.find_all(exp.Table)
                    if table.find_ancestor(exp.Select) is select
                ]
                for table in schema.tables:
                    if table.name.lower() in visible_tables and any(
                        any(
                            token in column.name.lower()
                            for token in SENSITIVE_COLUMN_TOKENS
                        )
                        for column in table.columns
                    ):
                        raise SQLValidationError(
                            "Wildcard selection is blocked because the table contains sensitive-looking columns."
                        )
                    if table.name.lower() in visible_tables and len(table.columns) > 12:
                        raise SQLValidationError(
                            "Wildcard selection is blocked for wide tables. Select only the needed columns."
                        )
    return tree.sql(dialect=_dialect(dialect))


def validation_warnings(
    sql: str, dialect: str, schema: SchemaInfo
) -> list[str]:
    """Report common numeric and conversion pitfalls without rejecting safe SQL."""
    try:
        tree = sqlglot.parse_one(sql, read=_dialect(dialect))
    except sqlglot.errors.ParseError:
        return []
    warnings: set[str] = set()
    column_types = {
        (table.name.lower(), column.name.lower()): column.data_type.lower()
        for table in schema.tables
        for column in table.columns
    }

    def column_type(node: exp.Expression) -> str | None:
        if not isinstance(node, exp.Column):
            return None
        if node.table:
            return next(
                (
                    dtype
                    for (table, name), dtype in column_types.items()
                    if name == node.name.lower() and table == node.table.lower()
                ),
                None,
            )
        found = {
            dtype
            for (table, name), dtype in column_types.items()
            if name == node.name.lower()
        }
        return next(iter(found)) if len(found) == 1 else None

    def is_integer_operand(node: exp.Expression) -> bool:
        if isinstance(node, exp.Literal) and not node.is_string:
            return "." not in node.this and "e" not in node.this.lower()
        dtype = column_type(node)
        return bool(
            dtype
            and any(
                dtype.startswith(token)
                for token in ("tinyint", "smallint", "integer", "int", "bigint", "bit")
            )
            and not any(token in dtype for token in ("decimal", "numeric", "float", "double", "real"))
        )

    if _dialect(dialect) == "tsql":
        for average in tree.find_all(exp.Avg):
            if is_integer_operand(average.this):
                warnings.add(
                    "T-SQL AVG over an integer may truncate fractional results; cast the input to DECIMAL."
                )
    for division in tree.find_all(exp.Div):
        if is_integer_operand(division.this) and is_integer_operand(division.expression):
            warnings.add(
                "Integer division may truncate fractional results; cast an operand to a decimal type."
            )
    for nullif in tree.find_all(exp.Nullif):
        parent = nullif.parent
        valid_divisor = isinstance(parent, exp.Div) and parent.expression is nullif
        has_subtraction = nullif.this.find(exp.Sub) is not None
        if not valid_divisor or has_subtraction:
            warnings.add(
                "NULLIF should only guard a division denominator, not a numerator or subtraction."
            )
    if _dialect(dialect) == "tsql":
        for comparison in tree.find_all((exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)):
            left, right = comparison.this, comparison.expression
            pair = ((left, right), (right, left))
            for column, literal in pair:
                dtype = column_type(column)
                if not dtype or not isinstance(literal, exp.Literal):
                    continue
                numeric_type = any(
                    dtype.startswith(token)
                    for token in ("int", "decimal", "numeric", "float", "real", "money")
                )
                text_type = any(token in dtype for token in ("char", "text", "string"))
                if (numeric_type and literal.is_string) or (
                    text_type and not literal.is_string
                ):
                    warnings.add(
                        "This T-SQL comparison may implicitly convert a value; cast the literal or column explicitly."
                    )
                    break
    return sorted(warnings)


def _dialect(dialect: str) -> str:
    return {
        "postgres": "postgres",
        "postgresql": "postgres",
        "mssql": "tsql",
        "sqlserver": "tsql",
        "duckdb": "duckdb",
        "sqlite": "sqlite",
        "mysql": "mysql",
    }.get(dialect.lower(), dialect.lower())


def _check_schema(tree: exp.Expression, schema: SchemaInfo) -> None:
    """Reject unknown tables and columns when names can be resolved safely."""
    table_names = {table.name.lower(): table.name for table in schema.tables}
    column_names = {
        table.name.lower(): {
            column.name.lower(): column.name for column in table.columns
        }
        for table in schema.tables
    }
    ctes = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    cte_columns = {
        cte.alias_or_name.lower(): {
            projection.alias_or_name.lower(): projection.alias_or_name
            for projection in getattr(cte.this, "expressions", [])
            if projection.alias_or_name
        }
        for cte in tree.find_all(exp.CTE)
    }
    if not table_names:
        return
    aliases_by_scope = {}
    sources_by_scope = {}
    select_aliases_by_scope = {}
    for select in tree.find_all(exp.Select):
        scope_aliases: dict[str, dict[str, str]] = {}
        scope_sources: list[dict[str, str]] = []
        for table in select.find_all(exp.Table):
            if table.find_ancestor(exp.Select) is not select:
                continue
            name = table.name.lower()
            if name in ctes:
                cols = cte_columns.get(name, {})
            else:
                if name not in table_names:
                    raise SQLValidationError(f"Unknown table: {table.name}.")
                canonical = table_names[name]
                table.set(
                    "this",
                    exp.to_identifier(
                        canonical, quoted=bool(table.this.args.get("quoted"))
                    ),
                )
                cols = column_names[name]
                scope_aliases[name] = cols
            scope_aliases[table.alias_or_name.lower()] = cols
            scope_sources.append(cols)
        aliases_by_scope[id(select)] = scope_aliases
        sources_by_scope[id(select)] = scope_sources
        select_aliases_by_scope[id(select)] = {
            item.alias.lower()
            for item in select.find_all(exp.Alias)
            if item.alias and item.find_ancestor(exp.Select) is select
        }
    for column in tree.find_all(exp.Column):
        name = column.name.lower()
        if not name or name == "*":
            continue
        select = column.find_ancestor(exp.Select)
        if select is None:
            raise SQLValidationError("Could not resolve the query column scope.")
        scope_aliases = aliases_by_scope[id(select)]
        scope_sources = sources_by_scope[id(select)]
        if (
            not column.table
            and name in select_aliases_by_scope[id(select)]
            and column.find_ancestor(exp.Order, exp.Group) is not None
        ):
            continue
        if column.table:
            allowed = scope_aliases.get(column.table.lower())
            if allowed is not None and name not in allowed:
                raise SQLValidationError(
                    f"Unknown column: {column.table}.{column.name}."
                )
            if allowed is None:
                raise SQLValidationError(f"Unknown table alias: {column.table}.")
            if allowed is not None:
                column.set(
                    "this",
                    exp.to_identifier(
                        allowed[name], quoted=bool(column.this.args.get("quoted"))
                    ),
                )
        else:
            candidates = [cols[name] for cols in scope_sources if name in cols]
            if not candidates:
                raise SQLValidationError(f"Unknown column: {column.name}.")
            canonical = set(candidates)
            if len(candidates) > 1:
                raise SQLValidationError(
                    f"Ambiguous column: {column.name}. Qualify it with a table alias."
                )
            column.set(
                "this",
                exp.to_identifier(
                    next(iter(canonical)), quoted=bool(column.this.args.get("quoted"))
                ),
            )
