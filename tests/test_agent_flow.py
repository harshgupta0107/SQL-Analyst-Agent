import json
import pandas as pd
from connectors.base import ColumnInfo, SchemaInfo, TableInfo
from agent.graph import SQLAnalystAgent


class Connector:
    name = "mock"
    dialect = "duckdb"

    def get_schema(self):
        return SchemaInfo([TableInfo("sales", [ColumnInfo("amount", "INTEGER")])])

    def run_query(self, sql, max_rows, timeout):
        return pd.DataFrame({"total": [5]})


class MockLLM:
    provider = "groq"

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = 0

    def generate(self, *args, **kwargs):
        self.calls += 1
        return next(self.outputs)


def test_agent_query_success():
    llm = MockLLM(
        [
            json.dumps(
                {"sql": "SELECT SUM(amount) AS total FROM sales", "assumptions": []}
            )
        ]
    )
    result = SQLAnalystAgent(llm).ask("total sales", Connector())
    assert result.kind == "data" and result.frame.iloc[0, 0] == 5


def test_schema_question_does_not_call_llm():
    llm = MockLLM([])
    result = SQLAnalystAgent(llm).ask("what tables do I have?", Connector())
    assert result.kind == "schema" and "sales" in result.answer and llm.calls == 0


def test_retries_sql_error_then_succeeds():
    llm = MockLLM(
        [
            json.dumps({"sql": "DELETE FROM sales", "assumptions": []}),
            json.dumps(
                {"sql": "SELECT SUM(amount) AS total FROM sales", "assumptions": []}
            ),
        ]
    )
    result = SQLAnalystAgent(llm).ask("total sales", Connector())
    assert result.kind == "data"
    assert llm.calls == 3  # invalid draft, valid draft, and result summary
    assert result.retry_count == 1


def test_switches_to_gemini_after_repeated_sql_failures():
    llm = MockLLM(
        [
            json.dumps({"sql": "DELETE FROM sales", "assumptions": []}),
            json.dumps({"sql": "UPDATE sales SET amount=0", "assumptions": []}),
            json.dumps(
                {"sql": "SELECT SUM(amount) AS total FROM sales", "assumptions": []}
            ),
        ]
    )
    result = SQLAnalystAgent(llm).ask("total sales", Connector())
    assert result.kind == "data"
    assert llm.provider == "gemini"


class ConnectorWithMeasures(Connector):
    def get_schema(self):
        return SchemaInfo(
            [
                TableInfo(
                    "sales",
                    [
                        ColumnInfo("quantity", "INTEGER"),
                        ColumnInfo("unit_price", "DOUBLE"),
                    ],
                )
            ]
        )


def test_ambiguous_measure_prompts_for_clarification():
    llm = MockLLM([])
    result = SQLAnalystAgent(llm).ask("sales", ConnectorWithMeasures())
    assert result.kind == "clarify"
    assert len(result.suggestions) <= 3
    assert llm.calls == 0


def test_time_sensitive_comparison_asks_one_period_question():
    result = SQLAnalystAgent(MockLLM([])).ask("How did sales change?", Connector())
    assert result.kind == "clarify"
    assert result.suggestions == [
        "Month over month",
        "Quarter over quarter",
        "Year over year",
    ]


def test_empty_results_are_explained():
    class EmptyConnector(Connector):
        def run_query(self, sql, max_rows, timeout):
            return pd.DataFrame(columns=["total"])

    llm = MockLLM(
        [
            json.dumps(
                {
                    "sql": "SELECT amount FROM sales WHERE amount > 100",
                    "assumptions": [],
                }
            )
        ]
    )
    result = SQLAnalystAgent(llm).ask("sales over 100", EmptyConnector())
    assert result.kind == "data"
    assert "no rows" in result.answer.lower()


def test_provider_outage_shows_retry_action():
    class OfflineLLM:
        provider = "groq"

        def generate(self, *args, **kwargs):
            raise RuntimeError(
                "Both AI providers are unavailable. Please retry in a moment."
            )

    result = SQLAnalystAgent(OfflineLLM()).ask("total sales", Connector())
    assert result.kind == "provider_error"
    assert result.suggestions == ["total sales"]


def test_clarification_answer_keeps_original_request_context():
    class CapturingLLM(MockLLM):
        last_messages = None

        def generate(self, messages, **kwargs):
            self.last_messages = messages
            return super().generate(messages, **kwargs)

    llm = CapturingLLM(
        [
            json.dumps(
                {
                    "sql": "SELECT SUM(quantity * unit_price) AS total FROM sales",
                    "assumptions": [],
                }
            )
        ]
    )
    agent = SQLAnalystAgent(llm)
    clarification = agent.ask("sales", ConnectorWithMeasures())
    assert clarification.kind == "clarify"
    response = agent.ask("Show revenue", ConnectorWithMeasures())
    assert response.kind == "data"
    assert "earlier request: sales" in llm.last_messages[-1]["content"]
