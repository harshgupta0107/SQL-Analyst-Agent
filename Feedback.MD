General feedback on the SQL Analyst Agent after testing it on a live database (Microsoft Fabric / T-SQL). Please apply these improvements across the whole app, add tests for each, and don't break existing behaviour.

WHAT IS WORKING (keep)
- Database connection and dialect-aware SQL (TOP vs LIMIT, T-SQL date functions).
- Clean CTE structure, correct joins, window functions and aggregations.
- Read-only validation and row caps.

IMPROVEMENTS NEEDED

1. Schema context must reveal real data values, not just the first rows
   - For every low-cardinality text/categorical column (about 15 distinct values or fewer), include ALL distinct values in the schema given to the model. Sample values taken from the first few rows are misleading.
   - Fetch them with SELECT DISTINCT (TOP n or LIMIT n per dialect), cache per connection, and refresh when the schema is refreshed.
   - Include value ranges for dates and numbers (min/max) so the model knows what period and scale the data covers.

2. Treat record-state columns carefully
   - Detect status/state/flag columns (status, is_active, is_deleted, cancelled, void, etc.). For business-activity questions (revenue, sales, completed work), exclude cancelled/deleted/inactive records by default unless the user asks otherwise.
   - Only filter on values that actually exist in the data; never guess spellings.
   - Always state the choice in the assumptions.

3. Assumptions must always be visible
   - Every answer must show the assumptions the model made (metric definitions, filters applied or not applied, date interpretation, ambiguous terms).
   - Feed the assumptions into the insight summary so key ones appear in the plain-English answer.
   - If a question is ambiguous in a way that changes the numbers, ask one short clarifying question instead of silently choosing.

4. Dialect-specific correctness
   - Maintain a short per-dialect rules list in prompts (e.g. integer AVG truncation in T-SQL, date arithmetic, string functions, quoting) and inject the one that matches the active source.
   - Use NULLIF only on divisors, never on numerators or in subtractions.
   - Add validator warnings for known pitfalls (integer division, AVG over integers, implicit type conversions).

5. Verify results before presenting them
   - Sanity-check results: empty output, all-NULL columns, row-cap truncation, negative values where impossible, percentages that don't sum sensibly.
   - Where cheap, run a reconciliation query (e.g. grand total vs sum of groups) and mention any mismatch.
   - If the result looks suspicious, retry or warn the user instead of presenting it confidently.

6. Self-correction and transparency
   - On validation or execution errors, retry with the exact error, then fall back to the second model, then explain plainly.
   - Show the user what happened (e.g. "Retried once after a column error"), and always show the SQL that was executed and the real result table.
   - Never state a number in the narrative that isn't in the result set.

7. Connection robustness
   - Create one engine per session and reuse it; never reconnect (or re-trigger a login popup) per question.
   - Support more than one auth mode per connector (interactive for local, service principal or token for deployment).
   - Give plain-English, actionable errors for login failures, blocked ports, missing drivers and timeouts.
   - Keep credentials in session memory or .env only; never log them.

8. Prompt and config hygiene
   - Keep all prompts in prompts.py; make sure prompt changes take effect on restart and aren't cached.
   - Keep every prompt placeholder in sync with the code that fills it (add tests that format each template).
   - Log the schema text and prompt version used for each answer (without secrets) so wrong answers can be debugged quickly.

9. Testing
   - Add a golden-question test suite on a small sample dataset covering: joins across 3+ tables, window functions, date filters, status filtering, percentages of total, averages with decimals, and follow-up questions.
   - Compare result values, not SQL text. Include prompt-injection and read-only security tests.

When finished, summarise what changed per item above and list anything you chose not to implement and why.