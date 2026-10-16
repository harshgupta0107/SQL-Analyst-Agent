import pandas as pd
from connectors.file_loader import FileDataConnector


def test_csv_loader_header_dedup_and_leading_zero():
    c = FileDataConnector()
    data = b"Report title,,\nID,Name,Name\n001,Alice,North\n002,Bob,South\n"
    info = c.load_file("customers.csv", data)[0]
    assert info["columns"] == ["id", "name", "name_2"]
    assert str(c.get_sample_rows(info["table"]).iloc[0, 0]) == "001"
    assert info["mapping"]["Name"] == ["name", "name_2"]
    c.close()


def test_excel_every_sheet(tmp_path):
    path = tmp_path / "book.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"Order ID": [1], "Total": [3]}).to_excel(
            writer, index=False, sheet_name="Orders"
        )
        pd.DataFrame({"Customer": ["A"]}).to_excel(
            writer, index=False, sheet_name="Customers"
        )
    c = FileDataConnector()
    loaded = c.load_file("book.xlsx", path.read_bytes())
    assert {x["table"] for x in loaded} == {"book_orders", "book_customers"}
    c.close()


def test_encoding_delimiter_empty_rows_and_replace_confirmation():
    c = FileDataConnector()
    data = "Title\t\t\nCustomer ID\tName\tRegion\n001\tJos\u00e9\tWest\n\t\t\n".encode(
        "latin-1"
    )
    preview = c.load_file("clients.tsv", data)[0]
    assert preview["columns"] == ["customer_id", "name", "region"]
    assert str(c.get_sample_rows("clients").iloc[0, 0]) == "001"
    try:
        c.load_file("clients.tsv", data)
    except FileExistsError as exc:
        assert "clients" in str(exc)
    else:
        raise AssertionError("Existing data must require explicit confirmation")
    c.load_file("clients.tsv", data, replace=True)
    c.close()


def test_sensitive_values_are_hidden_from_file_preview():
    c = FileDataConnector()
    preview = c.load_file("people.csv", b"name,email\nAsha,secret@example.test\n")[0]
    assert preview["preview"].iloc[0]["email"] == "[hidden]"
    assert preview["mapping"]["email"] == ["email"]
    c.close()


def test_status_samples_are_available_for_prompt_rules():
    connector = FileDataConnector()
    connector.load_file(
        "orders.csv",
        b"order_id,order_status,is_active\n1,Cancelled,true\n2,Completed,false\n",
    )

    columns = {column.name: column for column in connector.get_schema().tables[0].columns}

    assert set(columns["order_status"].sample_values) == {"Cancelled", "Completed"}
    assert set(columns["is_active"].sample_values) == {"False", "True"}
    connector.close()


def test_file_schema_includes_categorical_values_and_numeric_range():
    connector = FileDataConnector()
    connector.load_file(
        "facts.csv",
        b"category,amount\nWest,10\nEast,4\nWest,7\n",
    )
    columns = {column.name: column for column in connector.get_schema().tables[0].columns}
    assert columns["category"].sample_values == ["East", "West"]
    assert columns["category"].values_complete
    assert columns["amount"].value_range == ("4", "10")
    connector.close()
