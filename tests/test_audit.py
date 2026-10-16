"""Audit log redaction tests."""

from agent.audit import redact_sql, redact_text


def test_redact_text_masks_credentials_identifiers_and_tokens():
    value = "password=hunter2 email alice@example.com token=gsk12345678901234567890"
    redacted = redact_text(value)

    assert "hunter2" not in redacted
    assert "alice@example.com" not in redacted
    assert "gsk12345678901234567890" not in redacted


def test_redact_sql_masks_string_values_and_sensitive_text():
    sql = "SELECT * FROM customers WHERE email = 'alice@example.com'"

    redacted = redact_sql(sql)

    assert "alice@example.com" not in redacted
    assert "[REDACTED]" in redacted
