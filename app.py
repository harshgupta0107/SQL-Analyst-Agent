"""Streamlit entry point for SQL Analyst Agent."""

from __future__ import annotations

import logging
import copy

import streamlit as st

from agent.graph import SQLAnalystAgent
from agent.llm import LLMClient
from config import get_settings
from ui.chat import render_response
from ui.sidebar import render_sidebar
from connectors.base import SENSITIVE_COLUMN_TOKENS

st.set_page_config(
    page_title="SQL Analyst", page_icon=":material/query_stats:", layout="wide"
)

try:
    settings = get_settings()
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

st.markdown(
    """
    <style>
      :root { --ink:#17223b; --muted:#64748b; --line:#e7edf4; --accent:#176b87; }
      .block-container {max-width: 1260px; padding-top: 2rem; padding-bottom: 3rem;}
      [data-testid="stSidebar"] {border-right: 1px solid var(--line);}
      .hero {padding: 1.35rem 1.6rem; border: 1px solid var(--line); border-radius: 18px;
        background: linear-gradient(120deg,#f2f8fb 0%,#ffffff 72%); margin-bottom: 1rem;}
      .hero-kicker {font-size:.76rem; font-weight:700; letter-spacing:.11em; color:var(--accent); text-transform:uppercase;}
      .hero-title {font-size:2rem; line-height:1.2; font-weight:750; color:var(--ink); margin:.35rem 0;}
      .hero-copy {font-size:1rem; color:var(--muted); margin:0;}
      div[data-testid="stChatMessage"] {border:1px solid var(--line); border-radius:14px; padding:.75rem 1rem;}
      div[data-testid="stChatInput"] {border-color:#cfdae5;}
      .source-pill {display:inline-block; border:1px solid #c9e2eb; background:#f1f9fb; border-radius:99px;
        color:#155b72; padding:.3rem .7rem; font-size:.82rem; font-weight:650;}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def _shared_llm_client():
    """Cache thread-safe SDK clients while sessions own separate routing state."""
    client = LLMClient(get_settings())
    client._clients()
    return client


@st.cache_data(show_spinner=False)
def _cached_schema(connection_id: str, revision: int, _connector):
    """Cache schema metadata by a session-unique connection identifier."""
    return _connector.get_schema()


if "llm" not in st.session_state:
    st.session_state.llm = copy.copy(_shared_llm_client())
if "history" not in st.session_state:
    st.session_state.history = []
if "agent" not in st.session_state:
    st.session_state.agent = SQLAnalystAgent(
        st.session_state.llm,
        settings.max_rows_returned,
        settings.query_timeout_seconds,
    )
if "sources" not in st.session_state:
    st.session_state.sources = {}

render_sidebar(settings)
active = st.session_state.get("active_source")
previous = st.session_state.get("previous_active_source")
if previous != active:
    st.session_state.agent.memory.clear()
    st.session_state.previous_active_source = active
connector = st.session_state.sources.get(active)

st.markdown(
    '<section class="hero"><div class="hero-kicker">SQL Analyst Agent</div>'
    '<div class="hero-title">Answers you can verify.</div>'
    '<p class="hero-copy">Ask a business question. Review the SQL and results behind every answer.</p></section>',
    unsafe_allow_html=True,
)

if connector:
    st.markdown(
        f'<span class="source-pill">Active source · {active}</span>',
        unsafe_allow_html=True,
    )
    if st.button("Refresh schema", key=f"refresh_schema_{active}"):
        schema = connector.refresh_schema()
        st.session_state.schema_revisions[active] += 1
    else:
        schema = _cached_schema(
            st.session_state.source_cache_ids[active],
            st.session_state.schema_revisions[active],
            connector,
        )
    sensitive_names = [
        column.name
        for table in schema.tables
        for column in table.columns
        if any(term in column.name.lower() for term in SENSITIVE_COLUMN_TOKENS)
    ]
    if sensitive_names:
        st.warning(
            "Sensitive-looking columns are blocked from queries: "
            + ", ".join(sensitive_names)
        )

    with st.expander(f"Explore schema · {len(schema.tables)} tables", expanded=False):
        for table in schema.tables:
            st.markdown(
                f"**{table.name}** · {table.row_count if table.row_count is not None else 'unknown'} rows"
            )
            st.caption(", ".join(f"{c.name} ({c.data_type})" for c in table.columns))
        join_hints = []
        for index, left in enumerate(schema.tables):
            for right in schema.tables[index + 1 :]:
                left_columns = {column.name.lower(): column for column in left.columns}
                for column in right.columns:
                    match = left_columns.get(column.name.lower())
                    if (
                        match
                        and str(match.data_type).lower()
                        == str(column.data_type).lower()
                    ):
                        join_hints.append(
                            f"{left.name}.{match.name} ↔ {right.name}.{column.name}"
                        )
        if join_hints:
            st.markdown("**Possible join keys**")
            st.caption(" · ".join(join_hints[:8]))

if st.session_state.get("upload_previews"):
    with st.expander("Recently loaded file previews", expanded=True):
        for preview in st.session_state.upload_previews:
            st.markdown(
                f"**{preview['table']}** · {preview['rows']:,} rows · "
                + ", ".join(
                    f"{name} ({preview['types'][name]})" for name in preview["columns"]
                )
            )
            st.dataframe(preview["preview"], use_container_width=True, hide_index=True)
            st.caption(
                "Business labels: "
                + "; ".join(
                    f"{clean} ← {original}"
                    for original, clean_names in preview["mapping"].items()
                    for clean in clean_names
                )
            )

if not st.session_state.history and connector:
    st.markdown("#### Start with a question")
    questions = []
    for table in schema.tables[:2]:
        questions.append(f"How many rows are in {table.name}?")
        numeric = next(
            (
                column.name
                for column in table.columns
                if any(
                    value in column.data_type.lower()
                    for value in ("int", "numeric", "decimal", "double", "float")
                )
            ),
            None,
        )
        if numeric:
            questions.append(f"What is the total {numeric.replace('_', ' ')}?")
    for index, question in enumerate(questions[:4]):
        if st.button(question, key=f"example_{index}"):
            st.session_state.queued_question = question
            st.rerun()
elif not connector and not st.session_state.history:
    st.info("Connect a source in the sidebar or load the demo dataset to begin.")

for index, item in enumerate(st.session_state.history):
    with st.chat_message(item["role"]):
        if item["role"] == "assistant":
            render_response(item["response"], key=f"history_{index}")
        else:
            st.markdown(item["content"])

typed_question = st.chat_input("Ask about your data…", disabled=connector is None)
queued_question = st.session_state.pop("queued_question", None)
question = typed_question or queued_question

if question:
    st.session_state.history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        try:
            with st.status(
                "Understanding question → Selecting data → Writing SQL → Running query",
                expanded=False,
            ):
                response = st.session_state.agent.ask(question, connector)
            render_response(response, key=f"turn_{len(st.session_state.history)}")
            st.session_state.history.append({"role": "assistant", "response": response})
        except Exception as exc:
            logging.error("Request failed (error_type=%s).", type(exc).__name__)
            st.error(
                "I couldn’t complete that request. Check the active source and try again."
            )
