import pandas as pd

from agent.verification import result_warnings


def test_flags_null_negative_and_incomplete_percentage_results():
    frame = pd.DataFrame(
        {
            "optional_value": [None, None],
            "quantity": [-2, 3],
            "share_pct": [20.0, 30.0],
        }
    )
    warnings = result_warnings(frame)
    assert any("only NULL" in warning for warning in warnings)
    assert any("negative values" in warning for warning in warnings)
    assert any("complete share breakdown" in warning for warning in warnings)


def test_ordinary_results_have_no_sanity_warnings():
    assert result_warnings(pd.DataFrame({"revenue": [25.5, 40.0]})) == []
