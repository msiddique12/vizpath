"""Tests for trace retention cleanup."""

from datetime import datetime, timedelta, timezone

from app.auth import hash_api_key
from app.models import CuratedLabel, Project, Span, Trace
from app.retention import prune_expired_traces


def test_prune_expired_traces_deletes_labels_and_keeps_recent_traces(test_db):
    project = Project(name="retention", api_key_hash=hash_api_key("vp_retention"))
    test_db.add(project)
    test_db.flush()

    now = datetime.now(timezone.utc)
    expired = Trace(
        id="trace-expired",
        project_id=project.id,
        name="expired",
        status="success",
        start_time=now - timedelta(days=10),
        created_at=now - timedelta(days=10),
    )
    recent = Trace(
        id="trace-recent",
        project_id=project.id,
        name="recent",
        status="success",
        start_time=now,
        created_at=now,
    )
    test_db.add_all([expired, recent])
    test_db.flush()
    test_db.add_all(
        [
            Span(
                id="span-expired",
                trace_id=expired.id,
                name="expired-step",
                start_time=now - timedelta(days=10),
            ),
            CuratedLabel(trace_id=expired.id, label="good", quality_score=90),
        ]
    )
    test_db.commit()

    deleted = prune_expired_traces(test_db, now=now, retention_days=7)
    test_db.commit()

    assert deleted == 1
    assert test_db.query(Trace).filter(Trace.id == "trace-expired").first() is None
    assert test_db.query(Span).filter(Span.trace_id == "trace-expired").first() is None
    assert test_db.query(CuratedLabel).filter(CuratedLabel.trace_id == "trace-expired").first() is None
    assert test_db.query(Trace).filter(Trace.id == "trace-recent").first() is not None
