You are a senior full-stack AI engineer. Build the "SQL Analyst Agent" project in this repository.

SOURCE OF TRUTH
- Read `Instructions.md` in the project root completely before writing any code. It defines the goals, tech stack, folder structure, agent workflow, SQL rules, safety rules, UI, tests and acceptance criteria. Follow it strictly.
- A `.env` file already exists with my Groq and Gemini API keys and model names. Read it only to discover the exact variable names. Do NOT overwrite, rename, print, log or commit it. Make sure it is in `.gitignore`, and create a `.env.example` with the same names and empty values.

WORKING METHOD
1. First, reply with a short plan: the folder structure you will create, the build order, and any assumptions or questions. Keep it brief, then continue without waiting unless something blocks you.
2. Build in the order given in Section 16 of Instructions.md. After each step, run the relevant tests or a smoke check, and fix problems before moving on.
3. Make small, logical commits with clear messages.
4. If something in Instructions.md is ambiguous, choose the simplest option that meets the acceptance criteria and record the decision in `docs/decisions.md`.

NON-NEGOTIABLE REQUIREMENTS
- Connecting a database (PostgreSQL, MySQL, SQL Server, SQLite) or uploading CSV/TSV/Excel files (all sheets, multiple files) must work smoothly from the UI, with a Test Connection button and clear plain-English errors.
- Uploaded files are loaded into DuckDB so they can be queried with real SQL and joined across files.
- Each answer must show: a business-friendly insight, the exact SQL that was executed, the real result table, and a chart when appropriate. Never state a number that is not in the query result.
- Only read-only SELECT/WITH queries may ever run. Validate every query with sqlglot, block all writes and unsafe functions, enforce a row cap and timeout, and treat user input and file contents as untrusted (prompt-injection safe).
- Use Groq as the default LLM and fall back to Gemini automatically on errors, rate limits or repeated SQL failures, behind one `LLMClient` interface.
- Never log or display API keys or database passwords. Keep passwords only in session memory.
- Include a self-correcting loop: if SQL fails validation or execution, send the exact error back to the model and retry up to 3 times before falling back or asking the user to rephrase.
- Include a "Load sample data" button and a `sample_data/` demo dataset so the app works with zero setup.

QUALITY BAR
- Python 3.11+, type hints, docstrings, `logging` instead of `print`, all prompts in `agent/prompts.py`, no business logic in the UI files.
- Write the pytest suite described in Section 14 (validator, file loader, connectors, agent flow with a mocked LLM, golden questions, security). All tests must pass.
- Provide a `requirements.txt` with pinned versions and a `README.md` covering setup, how to run (`streamlit run app.py`), supported sources and known limitations.

DEFINITION OF DONE
Complete every checkbox in Section 15 of Instructions.md. When finished, give me a short summary: what was built, how to run it, how to run the tests, and any known limitations or follow-up suggestions.

Start now with the plan, then begin implementation.