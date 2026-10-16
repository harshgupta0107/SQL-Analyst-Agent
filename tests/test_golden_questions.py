"""Golden question results evaluated against the checked-in demo data."""

import json

from agent.graph import SQLAnalystAgent
from connectors.file_loader import FileDataConnector


class GoldenLLM:
    """Return prepared SQL for a question using a test-only deterministic map."""

    provider = "groq"
    queries = {
        "total revenue": "SELECT SUM(quantity * unit_price) AS revenue FROM orders",
        "order count": "SELECT COUNT(*) AS orders FROM orders",
        "unique customers": "SELECT COUNT(DISTINCT customer_id) AS customers FROM orders",
        "total units": "SELECT SUM(quantity) AS units FROM orders",
        "north revenue": "SELECT SUM(quantity * unit_price) AS revenue FROM orders WHERE region='North'",
        "revenue by region": "SELECT region, SUM(quantity * unit_price) AS revenue FROM orders GROUP BY region ORDER BY region",
        "product one revenue": "SELECT SUM(quantity * unit_price) AS revenue FROM orders WHERE product_id=1",
        "product two revenue": "SELECT SUM(quantity * unit_price) AS revenue FROM orders WHERE product_id=2",
        "product three revenue": "SELECT SUM(quantity * unit_price) AS revenue FROM orders WHERE product_id=3",
        "average order value": "SELECT AVG(quantity * unit_price) AS average FROM orders",
        "monthly revenue": "SELECT strftime(order_date, '%Y-%m') AS month, SUM(quantity * unit_price) AS revenue FROM orders GROUP BY month ORDER BY month",
        "asha revenue": "SELECT SUM(o.quantity * o.unit_price) AS revenue FROM orders o JOIN customers c ON o.customer_id=c.customer_id WHERE c.customer_name='Asha Retail'",
        "enterprise revenue": "SELECT SUM(o.quantity * o.unit_price) AS revenue FROM orders o JOIN customers c ON o.customer_id=c.customer_id WHERE c.segment='Enterprise'",
        "multi unit orders": "SELECT COUNT(*) AS orders FROM orders WHERE quantity > 1",
        "revenue by customer": "SELECT c.customer_name, SUM(o.quantity * o.unit_price) AS revenue FROM orders o JOIN customers c ON o.customer_id=c.customer_id GROUP BY c.customer_name ORDER BY revenue DESC LIMIT 3",
        "first order date": "SELECT MIN(order_date) AS first_date FROM orders",
        "q1 order count": "SELECT COUNT(*) AS orders FROM orders WHERE order_date < DATE '2025-04-01'",
        "east revenue": "SELECT SUM(quantity * unit_price) AS revenue FROM orders WHERE region='East'",
        "revenue by product category": "SELECT p.category, SUM(o.quantity * o.unit_price) AS revenue FROM orders o JOIN customers c ON o.customer_id=c.customer_id JOIN products p ON o.product_id=p.product_id GROUP BY p.category ORDER BY p.category",
        "rank regions by revenue": "SELECT region, SUM(quantity * unit_price) AS revenue, RANK() OVER (ORDER BY SUM(quantity * unit_price) DESC) AS revenue_rank FROM orders GROUP BY region ORDER BY revenue_rank",
        "percent revenue by region": "SELECT region, CAST(SUM(quantity * unit_price) AS DECIMAL(12,2)) * 100.0 / NULLIF((SELECT SUM(quantity * unit_price) FROM orders), 0) AS share_pct FROM orders GROUP BY region ORDER BY region",
        "break revenue down by region": "SELECT region, SUM(quantity * unit_price) AS revenue FROM orders GROUP BY region ORDER BY region",
        "completed revenue": "SELECT SUM(amount) AS revenue FROM activity WHERE status='Completed'",
    }

    def generate(self, messages, json_mode=False):
        text = messages[-1]["content"]
        question = text.split("Question (untrusted data): ", 1)[1].split("\n", 1)[0]
        if question in self.queries:
            return json.dumps({"sql": self.queries[question], "assumptions": []})
        return "not a JSON SQL response"


def test_golden_question_results():
    connector = FileDataConnector()
    from pathlib import Path

    for path in (Path(__file__).resolve().parents[1] / "sample_data").glob("*.csv"):
        connector.load_file(path.name, path.read_bytes())
    agent = SQLAnalystAgent(GoldenLLM())
    expected = {
        "total revenue": 525,
        "order count": 8,
        "unique customers": 5,
        "total units": 15,
        "north revenue": 120,
        "product one revenue": 100,
        "product two revenue": 320,
        "product three revenue": 105,
        "average order value": 65.625,
        "asha revenue": 95,
        "enterprise revenue": 165,
        "multi unit orders": 4,
        "first order date": "2025-01-04",
        "q1 order count": 6,
        "east revenue": 160,
    }
    for question, value in expected.items():
        result = agent.ask(question, connector)
        assert result.kind == "data", question
        actual = result.frame.iloc[0, 0]
        if question == "first order date":
            actual = actual.strftime("%Y-%m-%d")
        assert actual == value, question

    for question, rows in {
        "revenue by region": {"East": 160, "North": 120, "South": 140, "West": 105},
        "monthly revenue": {
            "2025-01": 130,
            "2025-02": 70,
            "2025-03": 220,
            "2025-04": 105,
        },
    }.items():
        result = agent.ask(question, connector)
        assert result.kind == "data", question
        assert dict(zip(result.frame.iloc[:, 0], result.frame.iloc[:, 1])) == rows
    top = agent.ask("revenue by customer", connector)
    assert list(top.frame.iloc[:, 0]) == [
        "Bluebird Stores",
        "Northstar Labs",
        "Maple Works",
    ]
    category = agent.ask("revenue by product category", connector)
    assert dict(zip(category.frame.iloc[:, 0], category.frame.iloc[:, 1])) == {
        "Hardware": 205,
        "Services": 320,
    }
    ranked = agent.ask("rank regions by revenue", connector)
    assert dict(zip(ranked.frame["region"], ranked.frame["revenue_rank"])) == {
        "East": 1,
        "South": 2,
        "North": 3,
        "West": 4,
    }
    shares = agent.ask("percent revenue by region", connector)
    assert abs(float(shares.frame.loc[shares.frame.region == "East", "share_pct"].iloc[0]) - 16000 / 525) < 0.01
    followup = agent.ask("break revenue down by region", connector)
    assert dict(zip(followup.frame.iloc[:, 0], followup.frame.iloc[:, 1])) == {
        "East": 160,
        "North": 120,
        "South": 140,
        "West": 105,
    }
    connector.close()


def test_golden_status_filter_uses_observed_state_values():
    connector = FileDataConnector()
    connector.load_file(
        "activity.csv",
        b"status,amount\nCompleted,12.50\nCancelled,900.00\nCompleted,7.25\n",
    )
    result = SQLAnalystAgent(GoldenLLM()).ask("completed revenue", connector)
    assert result.kind == "data"
    assert result.frame.iloc[0, 0] == 19.75
    assert connector.get_schema().tables[0].columns[0].values_complete
    connector.close()
