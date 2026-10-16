"""Chat history and result rendering."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st
from agent.graph import AgentResponse


def render_response(response: AgentResponse, key: str = "response") -> None:
    """Display answer, query, table, chart, and clickable next questions."""
    st.markdown(response.answer)
    if response.kind == "data":
        if response.retry_count:
            st.info(
                f"I corrected the query after {response.retry_count} retry attempt(s)."
            )
        for warning in response.warnings:
            st.warning(warning)
        with st.expander("Executed SQL", expanded=False):
            st.caption(f"Executed SQL · {response.dialect.upper()}")
            st.code(response.sql, language="sql")
        st.markdown("**Query results**")
        st.dataframe(
            response.frame,
            use_container_width=True,
            hide_index=True,
            height=min(420, max(130, 38 * (len(response.frame) + 1))),
        )
        st.download_button(
            "Download results as CSV",
            response.frame.to_csv(index=False),
            file_name="query_results.csv",
            mime="text/csv",
            key=f"download_{key}",
        )
        if response.truncated:
            st.info("The result reached the configured row cap and was truncated.")
        _render_chart(response)
        st.markdown(
            "**Assumptions**\n"
            + (
                "\n".join(f"- {item}" for item in response.assumptions)
                if response.assumptions
                else "- No additional assumptions were stated."
            )
        )

    if response.suggestions:
        title = (
            "**Choose an option**"
            if response.kind == "clarify"
            else "**Explore further**"
        )
        st.markdown(title)
        columns = st.columns(len(response.suggestions))
        for index, (column, question) in enumerate(zip(columns, response.suggestions)):
            if column.button(
                question,
                key=f"followup_{key}_{index}",
                use_container_width=True,
            ):
                st.session_state.queued_question = question
                st.rerun()


def _render_chart(response: AgentResponse) -> None:
    """Render a labeled chart for compact time series or category results."""
    if not response.chart:
        return
    frame = response.frame
    numeric = [c for c in frame if pd.api.types.is_numeric_dtype(frame[c])]
    if not numeric:
        return
    category = next((c for c in frame if c not in numeric), None)
    if response.chart == "line":
        x = category or frame.columns[0]
        fig = px.line(frame, x=x, y=numeric[0], title=f"{numeric[0]} over time")
    elif response.chart == "pie" and category:
        fig = px.pie(
            frame,
            names=category,
            values=numeric[0],
            title=f"{numeric[0]} by {category}",
        )
    elif category:
        fig = px.bar(
            frame,
            x=category,
            y=numeric[0],
            title=f"{numeric[0]} by {category}",
        )
    else:
        return
    fig.update_layout(
        xaxis_title=category or str(frame.columns[0]),
        yaxis_title=str(numeric[0]),
        yaxis_tickformat=",",
        margin=dict(l=12, r=12, t=54, b=12),
    )
    st.plotly_chart(fig, use_container_width=True)
