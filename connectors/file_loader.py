"""Load CSV, TSV, and Excel files into a session DuckDB database."""

from __future__ import annotations
import io
import re
import unicodedata
import csv
import threading
from pathlib import Path
import duckdb
import pandas as pd
from .base import (
    ColumnInfo,
    SchemaInfo,
    TableInfo,
    SENSITIVE_COLUMN_TOKENS,
    is_status_column,
)


def clean_name(value: object, used: set[str] | None = None) -> str:
    """Convert an arbitrary label to a safe, unique SQL identifier."""
    raw = (
        unicodedata.normalize("NFKD", str(value))
        .encode("ascii", "ignore")
        .decode()
        .lower()
        .strip()
    )
    base = re.sub(r"[^a-z0-9]+", "_", raw).strip("_") or "column"
    if base[0].isdigit():
        base = "col_" + base
    used = used if used is not None else set()
    candidate, i = base, 2
    while candidate in used:
        candidate, i = f"{base}_{i}", i + 1
    used.add(candidate)
    return candidate


def _read_delimited(data: bytes, suffix: str) -> pd.DataFrame:
    """Read delimited input, detecting encoding, delimiter, and title rows."""
    last: Exception | None = None
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            raw = data.decode(encoding)
            sep = "\t" if suffix == ".tsv" else _detect_delimiter(raw)
            frame = pd.read_csv(
                io.StringIO(raw), sep=sep, engine="python", header=None, dtype=str
            )
            break
        except Exception as exc:
            last = exc
    else:
        raise ValueError(
            "Could not read the delimited file. Check its encoding and delimiter."
        ) from last
    frame = frame.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)
    if frame.empty:
        raise ValueError("The file has no non-empty rows.")
    header_index = _guess_header_row(frame)
    headers = frame.iloc[header_index].fillna("").astype(str).tolist()
    out = frame.iloc[header_index + 1 :].copy()
    out.columns = headers
    return out.reset_index(drop=True)


def _guess_header_row(frame: pd.DataFrame) -> int:
    """Prefer a dense, distinct, text-like row over title and data rows."""
    ranked = []
    for index in range(min(12, len(frame))):
        values = frame.iloc[index].dropna().astype(str).str.strip()
        if len(values) < 2:
            continue
        numeric = pd.to_numeric(values, errors="coerce").notna().sum()
        text_like = len(values) - numeric
        score = len(values) * 2 + values.nunique() * 0.5 + text_like * 1.5 - numeric * 2
        ranked.append((score, -index))
    return -max(ranked)[1] if ranked else 0


def _detect_delimiter(raw: str) -> str:
    """Pick the delimiter producing the most consistent multi-column rows."""
    lines = [line for line in raw.splitlines()[:20] if line.strip()]
    candidates = [",", "\t", ";", "|"]
    scores = []
    for delimiter in candidates:
        counts = []
        for line in lines:
            try:
                counts.append(len(next(csv.reader([line], delimiter=delimiter))))
            except Exception:
                pass
        multi = [n for n in counts if n > 1]
        scores.append(
            (
                len(multi),
                max(multi.count(n) for n in set(multi)) if multi else 0,
                sum(multi),
                delimiter,
            )
        )
    return max(scores)[-1]


def _clean_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """Clean headers, remove empty values, and infer common types."""
    frame = frame.dropna(how="all").dropna(axis=1, how="all").copy()
    used: set[str] = set()
    mapping: dict[str, list[str]] = {}
    names = []
    for old in frame.columns:
        new = clean_name(old, used)
        mapping.setdefault(str(old), []).append(new)
        names.append(new)
    frame.columns = names
    for col in frame.columns:
        series = frame[col]
        if any(
            token in col
            for token in ("category", "region", "department", "team", "group")
        ):
            non_empty = series.notna().sum()
            if non_empty and series.isna().sum() / len(series) <= 0.5:
                frame[col] = series.ffill()
                series = frame[col]
        if pd.api.types.is_string_dtype(series.dtype) or series.dtype == object:
            values = series.dropna().astype(str).str.strip()
            if (
                len(values)
                and values.str.fullmatch(r"\d+").all()
                and values.str.startswith("0").any()
            ):
                frame[col] = series.astype("string")
                continue
            if len(values):
                numeric = pd.to_numeric(series, errors="coerce")
                if numeric.notna().sum() >= max(1, series.notna().sum() * 0.9):
                    frame[col] = numeric
                    continue
                dates = pd.to_datetime(series, errors="coerce", format="mixed")
                if dates.notna().sum() >= max(1, series.notna().sum() * 0.9):
                    frame[col] = dates
                    continue
                lower = series.astype("string").str.lower()
                if lower.dropna().isin(["true", "false", "yes", "no"]).all():
                    frame[col] = lower.map(
                        {"true": True, "yes": True, "false": False, "no": False}
                    ).astype("boolean")
    return frame, mapping


class FileDataConnector:
    """In-memory DuckDB connector for uploaded files."""

    name = "Uploaded files"
    dialect = "duckdb"

    def __init__(self):
        self.connection = duckdb.connect(database=":memory:")
        self.mappings: dict[str, dict[str, list[str]]] = {}
        self._tables: list[str] = []
        self._schema_cache: SchemaInfo | None = None

    @property
    def table_names(self) -> tuple[str, ...]:
        """Return registered table names for replacement preflight."""
        return tuple(self._tables)

    def target_table_names(self, filename: str, data: bytes) -> list[str]:
        """Return clean destination table names without mutating the database."""
        suffix = Path(filename).suffix.lower()
        if suffix in {".csv", ".tsv"}:
            return [clean_name(Path(filename).stem)]
        if suffix in {".xlsx", ".xls"}:
            try:
                book = pd.ExcelFile(
                    io.BytesIO(data), engine="openpyxl" if suffix == ".xlsx" else "xlrd"
                )
                return [
                    clean_name(f"{Path(filename).stem}_{sheet}")
                    for sheet in book.sheet_names
                ]
            except Exception as exc:
                raise ValueError(
                    f"Could not read workbook {filename}. Check that it is a valid Excel file."
                ) from exc
        raise ValueError("Supported file types are CSV, TSV, XLSX, and XLS.")

    def load_file(
        self,
        filename: str,
        data: bytes,
        max_upload_mb: int = 200,
        *,
        replace: bool = False,
    ) -> list[dict]:
        """Load every sheet in a file, replacing same-name tables, with a preview."""
        if len(data) > max_upload_mb * 1024 * 1024:
            raise ValueError(f"{filename} exceeds the {max_upload_mb} MB upload limit.")
        suffix = Path(filename).suffix.lower()
        sheets: dict[str, pd.DataFrame]
        if suffix in {".csv", ".tsv"}:
            sheets = {Path(filename).stem: _read_delimited(data, suffix)}
        elif suffix in {".xlsx", ".xls"}:
            try:
                sheets = pd.read_excel(
                    io.BytesIO(data),
                    sheet_name=None,
                    header=None,
                    dtype=object,
                    engine="openpyxl" if suffix == ".xlsx" else "xlrd",
                )
            except Exception as exc:
                raise ValueError(
                    f"Could not parse workbook {filename}. Check that it is a valid Excel file."
                ) from exc
            normalized = {}
            for sheet, frame in sheets.items():
                frame = (
                    frame.dropna(how="all")
                    .dropna(axis=1, how="all")
                    .reset_index(drop=True)
                )
                if frame.empty:
                    continue
                idx = _guess_header_row(frame)
                headers = frame.iloc[idx].fillna("").astype(str).tolist()
                body = frame.iloc[idx + 1 :].copy()
                body.columns = headers
                normalized[sheet] = body.reset_index(drop=True)
            sheets = normalized
        else:
            raise ValueError("Supported file types are CSV, TSV, XLSX, and XLS.")
        destinations = [
            clean_name(
                f"{Path(filename).stem}_{sheet}"
                if suffix in {".xlsx", ".xls"}
                else sheet
            )
            for sheet in sheets
        ]
        conflicts = sorted(set(destinations) & set(self._tables))
        if conflicts and not replace:
            raise FileExistsError(
                "Replacing these existing tables requires confirmation: "
                + ", ".join(conflicts)
            )
        previews = []
        for source_name, raw in sheets.items():
            frame, mapping = _clean_frame(raw)
            if frame.empty:
                continue
            table = clean_name(
                f"{Path(filename).stem}_{source_name}"
                if suffix in {".xlsx", ".xls"}
                else source_name
            )
            self.connection.register("_upload_frame", frame)
            self.connection.execute(
                f'CREATE OR REPLACE TABLE "{table}" AS SELECT * FROM _upload_frame'
            )
            self.connection.unregister("_upload_frame")
            if table not in self._tables:
                self._tables.append(table)
            self.mappings[table] = mapping
            safe_preview = frame.head(5).copy()
            for column in safe_preview.columns:
                if any(token in column.lower() for token in SENSITIVE_COLUMN_TOKENS):
                    safe_preview[column] = "[hidden]"
            previews.append(
                {
                    "table": table,
                    "rows": len(frame),
                    "columns": list(frame.columns),
                    "types": {c: str(t) for c, t in frame.dtypes.items()},
                    "preview": safe_preview,
                    "mapping": mapping,
                }
            )
        if not previews:
            raise ValueError("No usable sheets or rows were found in the file.")
        self._schema_cache = None
        return previews

    def test_connection(self) -> tuple[bool, str]:
        """Check DuckDB session health."""
        try:
            self.connection.execute("SELECT 1")
            return True, "File workspace is ready."
        except Exception:
            return False, "The file workspace is unavailable. Reload the files."

    def get_schema(self) -> SchemaInfo:
        """Return current table metadata and a few categorical values."""
        if self._schema_cache is not None:
            return self._schema_cache
        result = []
        for table in self._tables:
            desc = self.connection.execute(f'DESCRIBE "{table}"').fetchall()
            cols = []
            for name, dtype, *_ in desc:
                samples = []
                values_complete = False
                value_range = None
                sensitive = any(
                    token in name.lower() for token in SENSITIVE_COLUMN_TOKENS
                )
                lowered_type = dtype.lower()
                is_text = any(k in lowered_type for k in ("varchar", "text", "string"))
                if not sensitive and (is_status_column(name, dtype) or is_text):
                    escaped_name = name.replace('"', '""')
                    escaped_table = table.replace('"', '""')
                    values = [
                        row[0]
                        for row in self.connection.execute(
                            f'SELECT DISTINCT "{escaped_name}" FROM "{escaped_table}" WHERE "{escaped_name}" IS NOT NULL ORDER BY "{escaped_name}" LIMIT 16'
                        ).fetchall()
                    ]
                    values_complete = len(values) <= 15
                    samples = [
                        str(value)[:80]
                        for value in (values if values_complete else values[:3])
                    ]
                is_numeric_or_temporal = any(
                    token in lowered_type
                    for token in (
                        "int", "decimal", "numeric", "real", "float", "double",
                        "date", "time",
                    )
                )
                if not sensitive and is_numeric_or_temporal:
                    escaped_name = name.replace('"', '""')
                    escaped_table = table.replace('"', '""')
                    bounds = self.connection.execute(
                        f'SELECT MIN("{escaped_name}"), MAX("{escaped_name}") FROM "{escaped_table}"'
                    ).fetchone()
                    if bounds[0] is not None and bounds[1] is not None:
                        value_range = (str(bounds[0]), str(bounds[1]))
                original = next(
                    (
                        source
                        for source, clean_names in self.mappings[table].items()
                        if name in clean_names
                    ),
                    name,
                )
                cols.append(
                    ColumnInfo(
                        name,
                        dtype,
                        sample_values=samples,
                        original_name=original,
                        values_complete=values_complete,
                        value_range=value_range,
                    )
                )
            count = self.connection.execute(
                f'SELECT COUNT(*) FROM "{table}"'
            ).fetchone()[0]
            result.append(TableInfo(table, cols, count))
        self._schema_cache = SchemaInfo(result)
        return self._schema_cache

    def refresh_schema(self) -> SchemaInfo:
        """Invalidate and rebuild cached DuckDB schema metadata."""
        self._schema_cache = None
        return self.get_schema()

    def get_sample_rows(self, table: str, n: int = 3) -> pd.DataFrame:
        """Return a small sample of an existing table."""
        if table not in self._tables:
            raise ValueError("Unknown table.")
        return self.connection.execute(
            f'SELECT * FROM "{table}" LIMIT {max(0, int(n))}'
        ).df()

    def run_query(self, sql: str, max_rows: int, timeout: int) -> pd.DataFrame:
        """Run an already validated query under a DuckDB timeout and row cap."""
        timer = threading.Timer(max(1, int(timeout)), self.connection.interrupt)
        timer.daemon = True
        timer.start()
        try:
            frame = self.connection.execute(sql).df()
        finally:
            timer.cancel()
        truncated = len(frame) > max_rows
        frame = frame.head(max_rows)
        frame.attrs["truncated"] = truncated
        return frame

    def close(self) -> None:
        """Close the in-memory database."""
        self.connection.close()
