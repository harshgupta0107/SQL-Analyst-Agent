"""Chat history and polished result rendering for Streamlit."""

from __future__ import annotations

import logging
import re
from html import escape

import pandas as pd
import plotly.express as px
import streamlit as st

from agent.graph import AgentResponse

logger = logging.getLogger(__name__)


def render_response(
    response: AgentResponse,
    key: str = "response",
    runtime_seconds: float | None = None,
    model_name: str = "configured model",
) -> None:
    """Render an insight first, followed by assumptions and verifiable results."""
    if response.kind == "data" and response.frame is not None:
        frame = response.frame
        headline = _headline(response)
        if headline:
            st.markdown(f'<div class="answer-headline">{escape(headline)}</div>', unsafe_allow_html=True)
        st.markdown(response.answer)
        if response.assumptions:
            assumptions = "<br>".join(f"• {escape(str(item))}" for item in response.assumptions)
        else:
            assumptions = "• No additional assumptions were stated."
        st.markdown(
            f'<div class="assumptions-box"><strong>Assumptions used</strong><br>{assumptions}</div>',
            unsafe_allow_html=True,
        )
        if response.retry_count:
            st.info(f"Retried {response.retry_count} time(s) after a query error and corrected the SQL.")
        for warning in response.warnings:
            st.warning(warning)

        view = "Chart" if response.chart else "Table"
        if response.chart:
            view = st.radio(
                "Show result as",
                ["Chart", "Table"],
                horizontal=True,
                key=f"view_{key}",
                label_visibility="collapsed",
            )
        if view == "Chart" and response.chart:
            _render_chart(response)
        else:
            st.dataframe(
                frame,
                use_container_width=True,
                hide_index=True,
                height=min(520, max(180, 42 * min(len(frame) + 1, 11))),
                column_config=_column_config(frame),
            )
        left, right = st.columns([1, 1])
        left.download_button(
            "Download CSV",
            frame.to_csv(index=False),
            file_name="query_results.csv",
            mime="text/csv",
            key=f"download_{key}",
        )
        with left.expander("Copy table"):
            st.code(frame.to_csv(index=False, sep="\t"), language="text")
        with right.expander("Executed SQL", expanded=False):
            st.caption(f"Executed SQL · {response.dialect.upper()}")
            st.code(response.sql, language="sql")
        if response.truncated:
            st.info("The result reached the configured row cap and was truncated.")
        details = f"{len(frame):,} rows returned · {model_name}"
        if runtime_seconds is not None:
            details += f" · {runtime_seconds:.1f}s"
        if response.retry_count:
            details += f" · retried {response.retry_count} time(s)"
        st.markdown(f'<div class="answer-footer">{details}</div>', unsafe_allow_html=True)
        feedback_left, feedback_right, _ = st.columns([.65, .65, 6])
        if feedback_left.button("👍", key=f"feedback_up_{key}", help="This answer was useful"):
            _log_feedback("positive", response)
            st.toast("Thanks for the feedback.")
        if feedback_right.button("👎", key=f"feedback_down_{key}", help="This answer needs improvement"):
            _log_feedback("negative", response)
            st.toast("Thanks. The feedback was recorded.")
    else:
        st.markdown(response.answer)
        if response.error:
            st.info("You can try again or rephrase your question.")
            retry_col, rephrase_col = st.columns([1, 2])
            if retry_col.button("Try again", key=f"retry_{key}"):
                st.session_state.queued_question = st.session_state.get("last_question", "")
                st.rerun()
            replacement = rephrase_col.text_input("Rephrase", key=f"rephrase_{key}", label_visibility="collapsed", placeholder="Rephrase your question")
            if replacement and rephrase_col.button("Ask again", key=f"ask_rephrase_{key}"):
                st.session_state.queued_question = replacement
                st.rerun()
        if response.kind == "clarify" and response.suggestions:
            st.markdown("**Choose an option**")
        elif response.suggestions:
            st.markdown("**Explore further**")
        feedback_left, feedback_right, _ = st.columns([.65, .65, 6])
        if feedback_left.button("👍", key=f"feedback_up_{key}", help="This answer was useful"):
            _log_feedback("positive", response)
            st.toast("Thanks for the feedback.")
        if feedback_right.button("👎", key=f"feedback_down_{key}", help="This answer needs improvement"):
            _log_feedback("negative", response)
            st.toast("Thanks. The feedback was recorded.")

    suggestions = _relevant_suggestions(response)
    if suggestions:
        if response.kind not in {"clarify"}:
            st.markdown("**Explore further**")
        columns = st.columns(len(suggestions))
        for index, (column, question) in enumerate(zip(columns, suggestions)):
            if column.button(question, key=f"followup_{key}_{index}", use_container_width=True):
                st.session_state.queued_question = question
                st.rerun()


def _headline(response: AgentResponse) -> str:
    """Create a cautious headline from the returned values, without inventing metrics."""
    frame = response.frame
    if frame is None or frame.empty:
        return ""
    numeric = [column for column in frame if pd.api.types.is_numeric_dtype(frame[column])]
    categorical = [column for column in frame if column not in numeric]
    if len(frame) == 1 and len(numeric) == 1:
        column = numeric[0]
        value = frame.iloc[0][column]
        return f"{column.replace('_', ' ').title()}: {_display_number(value)}"
    if numeric and categorical:
        measure = next((column for column in numeric if any(x in column.lower() for x in ("revenue", "sales", "amount", "total", "spend"))), numeric[0])
        valid = pd.to_numeric(frame[measure], errors="coerce")
        if valid.notna().any():
            index = valid.idxmax()
            label = frame.loc[index, categorical[0]]
            share_column = next((column for column in numeric if any(x in column.lower() for x in ("pct", "percent", "share"))), None)
            share = ""
            if share_column:
                share_value = float(frame.loc[index, share_column])
                share = f" · {_display_percent(share_value)} of total"
            return f"Top {categorical[0].replace('_', ' ')}: {label} · {_display_number(frame.loc[index, measure])}{share}"
    return ""


def _column_config(frame: pd.DataFrame) -> dict:
    """Set readable units while preserving numeric table values and sorting."""
    config = {}
    currency = st.session_state.get("currency_symbol", "None")
    currency = "" if currency == "None" else currency
    for column in frame:
        if not pd.api.types.is_numeric_dtype(frame[column]):
            continue
        name = str(column).lower()
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        is_percent = any(token in name for token in ("pct", "percent", "percentage", "share", "rate"))
        if is_percent:
            as_fraction = values.empty or float(values.abs().max()) <= 1.01
            fmt = "percent" if as_fraction else "%.1f%%"
        elif any(token in name for token in ("revenue", "sales", "amount", "spend", "price", "average", "avg", "total")):
            fmt = f"{currency} %,.2f" if currency else ("localized" if st.session_state.get("indian_number_grouping") else "%,.2f")
        else:
            all_integer = values.map(lambda value: float(value).is_integer()).all()
            fmt = (
                "localized"
                if st.session_state.get("indian_number_grouping")
                else "%,.0f" if all_integer else "%,.2f"
            )
        config[column] = st.column_config.NumberColumn(str(column).replace("_", " ").title(), format=fmt)
    return config


def _display_number(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    currency = st.session_state.get("currency_symbol", "None")
    currency = "" if currency == "None" else currency + " "
    if st.session_state.get("indian_number_grouping", False):
        absolute = f"{abs(number):,.2f}"
        whole, decimal = absolute.split(".")
        head, tail = whole.rsplit(",", 1) if "," in whole else ("", whole)
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        formatted = (",".join(groups) + "," if groups else "") + tail + "." + decimal
        return currency + ("-" if number < 0 else "") + formatted
    return currency + f"{number:,.2f}"


def _display_percent(value: float) -> str:
    fraction = value if abs(value) <= 1.01 else value / 100
    return f"{fraction:.1%}"


def _render_chart(response: AgentResponse) -> None:
    """Render a labeled, bounded chart using result order for time series."""
    frame = response.frame
    if frame is None:
        return
    numeric = [column for column in frame if pd.api.types.is_numeric_dtype(frame[column])]
    categorical = [column for column in frame if column not in numeric]
    if not numeric or not categorical or len(frame) < 2:
        return
    measure, category = numeric[0], categorical[0]
    chart_frame = frame.copy()
    if response.chart == "line":
        figure = px.line(chart_frame, x=category, y=measure, markers=True, title=f"{measure.replace('_', ' ').title()} over time")
        figure.update_yaxes(tickformat=",.2f")
    else:
        chart_frame = chart_frame.sort_values(measure, ascending=False, kind="stable")
        if len(chart_frame) > 10:
            other = chart_frame.iloc[10:][numeric].sum(numeric_only=True).to_dict()
            other[category] = "Other"
            chart_frame = pd.concat([chart_frame.iloc[:10], pd.DataFrame([other])], ignore_index=True)
        figure = px.bar(chart_frame, x=category, y=measure, title=f"{measure.replace('_', ' ').title()} by {category.replace('_', ' ')}")
        figure.update_yaxes(tickformat=",.2f")
    figure.update_layout(
        template="plotly_dark" if st.session_state.get("ui_theme", "Dark") == "Dark" else "plotly_white",
        xaxis_title=category.replace("_", " ").title(),
        yaxis_title=measure.replace("_", " ").title(),
        margin=dict(l=12, r=12, t=54, b=12),
        colorway=["#58C4DD", "#8B8AE6", "#55C79A"],
    )
    st.plotly_chart(figure, use_container_width=True)


def _relevant_suggestions(response: AgentResponse) -> list[str]:
    suggestions = response.suggestions or []
    frame = response.frame
    columns = {str(column).lower().replace("_", " ") for column in frame.columns} if frame is not None else set()
    filtered = []
    for suggestion in suggestions:
        normalized = suggestion.lower()
        if any(name and name in normalized for name in columns):
            continue
        top_n = re.search(r"top\s+(\d+)", normalized)
        if top_n and frame is not None and int(top_n.group(1)) > len(frame):
            continue
        if suggestion not in filtered:
            filtered.append(suggestion)
    return filtered[:3]


def _log_feedback(rating: str, response: AgentResponse) -> None:
    """Record a content-free feedback event for later quality review."""
    logger.info(
        "answer_feedback rating=%s kind=%s dialect=%s rows=%s retries=%s",
        rating,
        response.kind,
        response.dialect,
        len(response.frame) if response.frame is not None else 0,
        response.retry_count,
    )
