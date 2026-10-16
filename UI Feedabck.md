UI/UX feedback for the SQL Analyst Agent (Streamlit). Please improve the interface below without changing the agent logic, SQL generation or safety behaviour. Keep all existing functionality working, and test each change in the running app.

WHAT WORKS (keep)
- Sidebar data-source panel (connect database, upload files, load sample data, active source, disconnect).
- Chat layout with Executed SQL expander, results table, CSV download, Assumptions and "Explore further".
- Active-source chip and schema explorer.

1. CONSISTENT THEME (high priority)
- The white hero card ("Answers you can verify.") clashes with the dark theme. Make every surface follow one theme: set it in .streamlit/config.toml (primaryColor, backgroundColor, secondaryBackgroundColor, textColor, font) and style custom blocks with the same palette. Support light and dark.
- Raise contrast for secondary text (hero subtitle, sidebar helper text, table headers); the grey on dark is hard to read.
- Increase base font size slightly (sidebar labels and table text are too small), and use a clear type scale: title, section heading, body, caption.
- Hide the Streamlit "Deploy" button and dev toolbar (toolbarMode = "minimal").

2. LAYOUT AND ALIGNMENT
- Use st.set_page_config(layout="wide") with a centered content column of a sensible max width (about 900-1100px). The chat input bar is currently much wider than the chat content column; align them.
- Make the hero smaller and compact once the first question is asked (collapse it to a slim header with the active source), so answers get the space.
- Remove the duplication between the "Active source" chip at the top and the "Active source" dropdown in the sidebar: keep one primary place for switching, and show the active source as a small status badge (name, type, table count, green dot for connected).
- Put "Refresh schema" and "Explore schema" next to the status badge as small actions, not as separate full-width rows.

3. SIDEBAR / CONNECTION FLOW
- Add "Microsoft Fabric" as its own database type. Selecting it should show fields for server, database/warehouse, auth mode (Interactive / Service Principal) and the relevant fields, instead of making the user paste an ODBC string under "SQL Server". Keep the full-connection-string option under "Advanced".
- After "Test connection", show a clear inline result: green success with "Connected, N tables, M columns" or a plain-English error with a hint. Show a spinner while connecting (interactive login can take a while, and tell the user a Microsoft login window may open).
- Rename the "SQLAlchemy URL or ODBC connection string" label to something friendlier ("Connection string") with the help text in the tooltip.
- Show a connected source as a card with name, type, tables and a Disconnect button, instead of leaving the connect form open.
- Group the sidebar clearly: 1) Connect a source, 2) Active source, 3) Settings. Keep "Load sample data" visible but secondary.

4. ANSWER CARD (most important for business users)
- Lead with a real insight, not "The result contains 4 rows". For example, the answer should name the top region and its share, with the key numbers highlighted. Use st.metric or a bold headline for the main figure when the result is one or a few values.
- Order of elements inside every answer: headline insight, optional 2-3 key bullets, chart, result table, then expanders for SQL and assumptions. Keep SQL in an expander but add a copy button and show the dialect.
- Show the assumptions list directly under the answer in a compact "Assumptions used" box, not hidden below the table. Make sure status filters and metric definitions are included (currently only the discount_pct assumption is shown).
- Add a small footer line to each answer: rows returned, run time, model used, and a "retried N times" note when relevant.

5. RESULTS TABLE
- Format numbers: thousands separators, 2 decimals for money/averages, percentages shown as 83.2% not 0.832. Use st.dataframe column_config (NumberColumn with format) and detect columns by name/type (amount, revenue, spend, price, pct, share, rate).
- Support Indian number grouping (lakh/crore) as an optional setting in the sidebar, and a currency symbol setting (none by default; only add one when the user chooses it).
- Respect the order of the query result and let the user sort by clicking headers. Make the table taller (show up to about 10 rows before scrolling) and make the header row higher contrast.
- Keep the Download CSV button and add a "Copy table" option if easy.

6. CHARTS
- Auto-generate a chart when the shape fits: bar for category comparisons, line for time series, none for single values or wide tables. Use Plotly with titles, axis labels, formatted ticks and the app's theme colours. Add a small toggle to switch between table and chart.
- Sort bar charts by value descending, and limit categories to the top 10 plus "Other".

7. "EXPLORE FURTHER" SUGGESTIONS
- Suggestions are currently generic and sometimes wrong (for example "Break this down by region" on a result that is already by region, "trend using signup date" which is unrelated to revenue, "Show the top 5 results" on a 4-row result).
- Generate 2-3 follow-ups with the model from the question, result columns and schema, and validate them: don't repeat the current breakdown, don't suggest a top N larger than the row count, only suggest dimensions and dates that are relevant to the metric.
- Clicking one must send it as the next question in the chat.

8. PROGRESS AND FEEDBACK STATES
- Show a live status block while working (st.status), with steps: Understanding question, Writing SQL, Running query, Summarising, and mark each done. The user currently sees nothing between question and answer.
- Friendly empty state: short welcome, how to connect data, and 4-5 example questions generated from the connected schema (clickable).
- Friendly error cards (not red stack traces) with a "Try again" and "Rephrase" action.
- Add 👍/👎 feedback buttons on every answer and log them (without secrets) for later evaluation.

9. CHAT EXPERIENCE
- Add a "New chat" / "Clear conversation" button, and keep the conversation scrolled to the latest answer.
- Show a clarifying question as buttons (options) rather than free text when the agent needs to ask one.
- Differentiate user and assistant messages more clearly with consistent avatars and spacing, and put a little breathing room between turns.
- Make the chat input placeholder helpful, for example "Ask a question about your data, e.g. total revenue by region".

10. ACCESSIBILITY AND POLISH
- Use readable minimum font sizes, sufficient colour contrast (WCAG AA), and don't rely on colour alone for success/error states.
- Keep the layout usable on a laptop screen (about 1366px wide) and don't let the sidebar push content off screen.
- Keep all custom CSS in one place (ui/styles.py or a CSS file) and keep UI code free of business logic.

ACCEPTANCE CHECKS
- Whole app uses one consistent theme; no white block on the dark background.
- After asking "total net revenue by region", the answer shows a headline insight naming the top region, a bar chart sorted descending, a table with formatted numbers (154,200 style), assumptions covering the status filter, and relevant follow-up suggestions.
- Fabric can be connected through a dedicated form without pasting a connection string.
- Progress steps are visible while a question runs.
- Chat input is aligned with the content column, and the Deploy button is hidden.

When finished, list what you changed per numbered item and include before/after screenshots if possible.