"""Security helper tests."""

import json
import logging

from app.security import audit_log


def test_audit_log_redacts_sensitive_fields(caplog):
    with caplog.at_level(logging.INFO, logger="app.security.audit"):
        audit_log(
            "test_event",
            request_id="req-123",
            api_key="vp_secret_key",
            project_id="project-1",
        )

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert message.startswith("audit_event ")
    payload = json.loads(message[len("audit_event "):])

    assert payload["event"] == "test_event"
    assert payload["request_id"] == "req-123"
    assert payload["project_id"] == "project-1"
    assert payload["api_key"] == "[REDACTED]"
    assert "vp_secret_key" not in message
