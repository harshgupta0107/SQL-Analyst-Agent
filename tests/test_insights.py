"""Grounded result summary tests."""

import pandas as pd

from agent.insights import summarize


def test_summary_highlights_maximum_from_result_rows_only():
    frame = pd.DataFrame({"region": ["North", "South"], "revenue": [1200, 1900]})

    answer = summarize("Compare revenue by region", frame)

    assert "1,900" in answer
    assert "South" in answer
    assert "highest" in answer


def test_summary_reports_small_single_row_breakdown():
    frame = pd.DataFrame({"region": ["West"], "orders": [17], "revenue": [825.5]})

    answer = summarize("Show west", frame)

    assert "West" in answer
    assert "17" in answer


def test_summary_uses_insight_prompt_and_includes_assumptions():
    class SummaryLLM:
        messages = None

        def generate(self, messages):
            self.messages = messages
            return "Revenue was 1,200 after excluding cancelled orders."

    llm = SummaryLLM()
    frame = pd.DataFrame({"revenue": [1200]})
    answer = summarize(
        "What was revenue?", frame, llm, ["Excluded cancelled orders"]
    )

    assert answer.startswith("Revenue was 1,200")
    assert "INSIGHT" not in llm.messages[0]["content"]
    assert "Excluded cancelled orders" in llm.messages[1]["content"]
    assert "1200" in llm.messages[1]["content"]


def test_summary_falls_back_when_model_invents_a_number():
    class HallucinatingLLM:
        def generate(self, messages):
            return "Revenue was 999."

    answer = summarize("What was revenue?", pd.DataFrame({"revenue": [12]}), HallucinatingLLM())

    assert answer == "Revenue: 12"
