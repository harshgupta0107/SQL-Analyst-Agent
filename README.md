# SQL Analyst Agent

A Streamlit analyst that connects to read-only relational databases or loads CSV, TSV, and Excel workbooks into DuckDB. Answers include the executed SQL and actual query result.

## Setup

Requires Python 3.11 or newer. Create a virtual environment, then install pinned dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

The project `.env` expects `GROQ_API_KEY`, `GROQ_MODEL`, `GEMINI_API_KEY`, and `GEMINI_MODEL`. Copy `.env.example` to create your own configuration. Optional settings control result rows, timeouts, upload size, and log level.

## Run

```powershell
streamlit run app.py
```

Use the sidebar to test a PostgreSQL, MySQL/MariaDB, SQL Server, or SQLite connection; upload one or more CSV, TSV, XLSX, or XLS files; or load sample data. Uploaded files (and every non-empty Excel sheet) become queryable DuckDB tables. The sample files demonstrate joins between orders and customers. SQL Server connections also require Microsoft's **ODBC Driver 18 for SQL Server** installed on the host; installing the Python `pyodbc` package alone does not install that system driver.

### Microsoft Fabric

Fabric Warehouse and Lakehouse SQL analytics endpoints use the SQL Server connector. Choose **SQL Server → Use a full connection string** and paste a complete ODBC connection string copied from Fabric, configured for Microsoft Entra authentication (for example, `Authentication=ActiveDirectoryServicePrincipal`). The advanced field is masked and accepts native ODBC strings as well as SQLAlchemy URLs. Include the Fabric server, database/item name, port 1433, and the identity's authentication properties. SQL authentication is not supported by Fabric; grant the Entra identity access to the Fabric item and install ODBC Driver 18 or later. The regular SQL Server username/password form is for SQL Server deployments using SQL authentication.

## Tests

```powershell
pytest
```

## Safety and limitations

The model is asked for one read-only SELECT and all SQL is parsed with sqlglot before execution. Results are capped; database users should still be configured read-only. Database passwords remain in the in-memory connector for the active Streamlit session. LLM provider credentials are loaded from `.env` and never shown in the UI. Persistent/multi-user connections are not supported. Automatic business metric definitions and robust database-specific cancellation of a long-running query require a domain glossary and per-driver tuning. SQLite and uploaded DuckDB data are exercised locally, and a Fabric Warehouse SQL endpoint has been live-tested. PostgreSQL, MySQL, and standalone SQL Server still need reachable endpoints for live verification.
