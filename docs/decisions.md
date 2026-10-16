# Decisions

- 2026-10-16: Used a small typed Python state machine for the agent so the retry and provider fallback behavior stays directly testable without adding graph-runtime complexity.
- 2026-10-16: Database dialects use SQLAlchemy and file uploads share an in-memory DuckDB connector. Credentials are held only in the session connector object.
- 2026-10-16: Re-uploading file tables is an explicit replacement action through the uploader flow; replacement is scoped to the current session.
- 2026-10-16: Connections and credentials are session scoped; sample data is loaded directly from CSV into DuckDB.
- 2026-10-16: Result summaries are generated deterministically from returned values instead of another model call, so an answer cannot introduce a numeric claim that is absent from the result.
