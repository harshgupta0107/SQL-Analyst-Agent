# Acceptance verification

Checked 2026-10-16 against `Instructions.md`.

| Requirement | Implementation / evidence | Status |
|---|---|---|
| Streamlit app and existing `.env` configuration | `app.py`, `config.py`; app startup smoke check and real provider requests | Met |
| PostgreSQL, MySQL, SQL Server, SQLite connection forms | SQLAlchemy connector, safe URL construction, driver diagnostics, read-only query enforcement | SQLite and Fabric live-tested; PostgreSQL, MySQL, and standalone SQL Server endpoints unavailable here |
| Microsoft Fabric SQL endpoint path | Native ODBC connection string, Entra interactive auth, ODBC Driver 18, schema introspection, and agent validator/executor | Live-verified: 4 tables, 17 columns, `SELECT 1`, and 3 result rows from a real table |
| CSV, TSV, XLSX/XLS loading and previews | DuckDB file connector, sheet loading, type/header cleanup, confirmation on replacement | Met; test suite includes loader cases |
| Answer + executed SQL + result table + useful chart | Chat renderer shows executed dialect/SQL, DataFrame, CSV export, and inferred chart; the new insight prompt summarizes bounded results and assumptions with numeric grounding | Met |
| Follow-ups and context | Session conversation memory, pending clarification, suggested question buttons | Met |
| SQL validation and read-only behavior | sqlglot allowlist, schema checks, sensitive-column guard, connector read-only settings | Met; validator/security tests pass |
| Groq default and Gemini fallback | `LLMClient`; mocked failover tests and live minimal API requests | Met |
| Friendly errors and no secrets in UI/logs | Safe UI messages, masked credentials/PII, redacted successful audit data, non-detail failure logging | Met |
| Sample data demo | Sidebar action loads sample orders and customers | Met |
| Golden questions, connector, flow, and security tests | `tests/` | Met: 53 passed |
| Setup, sources, and limitations documented | `README.md` | Met |
| PostgreSQL/MySQL/standalone SQL Server live integration | No configured reachable endpoints were available; Fabric Warehouse was tested separately | Not verified in this environment |

Verification run: `python -m pytest -q` (53 passed), `python -m ruff check .` (clean), and `python -m compileall -q .` (clean). The Streamlit server returned HTTP 200 on localhost. Real requests through `LLMClient` returned non-empty responses from both Groq and Gemini, including the new insight prompt with a grounded figure. No API keys or response contents are recorded here.

PostgreSQL, MySQL/MariaDB, and a standalone SQL Server instance remain unverified because no such endpoints were available. The Fabric Warehouse endpoint was tested separately over SQL Server TDS using Microsoft Entra interactive authentication.
