from ui.sidebar import _fabric_odbc_connection_string
from agent.graph import AgentResponse
from ui.chat import _column_config, _headline, _relevant_suggestions
import pandas as pd
import streamlit as st


def test_fabric_interactive_connection_string():
    connection = _fabric_odbc_connection_string(
        "sales.datawarehouse.fabric.microsoft.com", "SalesWH", "Interactive"
    )
    assert "Driver={ODBC Driver 18 for SQL Server}" in connection
    assert "Server=tcp:sales.datawarehouse.fabric.microsoft.com,1433" in connection
    assert "Database={SalesWH}" in connection
    assert "Authentication=ActiveDirectoryInteractive" in connection
    assert "PWD=" not in connection


def test_fabric_service_principal_connection_string_masks_values_and_escapes_braces():
    connection = _fabric_odbc_connection_string(
        "sales.fabric.microsoft.com",
        "SalesWH",
        "Service principal",
        "client-id",
        "secret}value",
        "tenant-id",
    )
    assert "Authentication=ActiveDirectoryServicePrincipal" in connection
    assert "UID={client-id}" in connection
    assert "PWD={secret}}value}" in connection
    assert "Authority Id={tenant-id}" in connection


def test_answer_headline_uses_returned_top_group_and_percentage():
    response = AgentResponse(
        "data",
        "Revenue by region",
        frame=pd.DataFrame(
            {"region": ["East", "West"], "revenue": [154200.0, 90000.0], "share_pct": [0.832, 0.168]}
        ),
    )
    headline = _headline(response)
    assert "East" in headline
    assert "154,200.00" in headline
    assert "83.2%" in headline


def test_numeric_column_formatting_and_duplicate_suggestion_filtering():
    st.session_state["currency_symbol"] = "None"
    st.session_state["indian_number_grouping"] = False
    frame = pd.DataFrame({"revenue": [154200.0], "share_pct": [0.832]})
    formats = _column_config(frame)
    assert formats["revenue"]["type_config"]["format"] == "%,.2f"
    assert formats["share_pct"]["type_config"]["format"] == "percent"
    response = AgentResponse(
        "data",
        "Revenue",
        frame=pd.DataFrame({"region": ["East"], "revenue": [10]}),
        suggestions=["Break this down by region", "Compare this with the previous period"],
    )
    assert _relevant_suggestions(response) == ["Compare this with the previous period"]
