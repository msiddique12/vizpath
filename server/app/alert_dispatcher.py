"""Background alert notification dispatcher."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from queue import Empty, Full, Queue
from uuid import UUID

import httpx

from app.config import settings
from app.database import get_db_session
from app.models import ProjectAlertEvent, ProjectAlertRule
from app.webhook_security import validate_webhook_target_url

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlertNotificationJob:
    """Queued webhook delivery job."""

    project_id: str
    rule_id: str
    destination_id: str
    destination_kind: str
    target_url: str
    secret_token: str | None
    rule_name: str
    metric: str
    operator: str
    threshold: float
    current_value: float
    generated_at: str


_queue: Queue[AlertNotificationJob] | None = None
_worker_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None
_lifecycle_lock = threading.Lock()


def _post_webhook_json(job: AlertNotificationJob) -> bool:
    try:
        safe_target_url = validate_webhook_target_url(
            job.target_url,
            allow_private_targets=settings.alert_webhook_allow_private_targets,
            resolve_dns=True,
        )
    except ValueError:
        logger.warning("Queued alert webhook target rejected by security policy")
        return False

    headers: dict[str, str] = {}
    if job.secret_token:
        headers["Authorization"] = f"Bearer {job.secret_token}"
    summary = (
        f"Vizpath alert breached: {job.rule_name} "
        f"({job.metric} {job.operator} {job.threshold}, current={job.current_value})"
    )
    if job.destination_kind == "webhook":
        body = {
            "type": "alert_breach",
            "generated_at": job.generated_at,
            "project_id": job.project_id,
            "rule": {
                "id": job.rule_id,
                "name": job.rule_name,
                "metric": job.metric,
                "operator": job.operator,
                "threshold": job.threshold,
            },
            "current_value": job.current_value,
        }
    elif job.destination_kind == "slack_webhook":
        body = {
            "text": summary,
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{summary}*",
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": (
                                f"project_id={job.project_id} • "
                                f"generated_at={job.generated_at}"
                            ),
                        }
                    ],
                },
            ],
        }
    else:
        logger.warning("Unsupported alert destination kind: %s", job.destination_kind)
        return False
    try:
        response = httpx.post(
            safe_target_url,
            json=body,
            headers=headers or None,
            timeout=5.0,
            follow_redirects=False,
            trust_env=False,
        )
        return 200 <= response.status_code < 300
    except Exception:
        logger.warning("Queued alert webhook delivery failed", exc_info=True)
        return False


def _record_job_outcome(job: AlertNotificationJob, delivered: bool) -> None:
    now = datetime.now(timezone.utc)
    try:
        rule_uuid = UUID(job.rule_id)
        destination_uuid = UUID(job.destination_id)
        project_uuid = UUID(job.project_id)
    except ValueError:
        logger.warning("Skipping delivery outcome write for invalid job IDs")
        return

    with get_db_session() as db:
        event_type = "notification_sent" if delivered else "notification_failed"
        db.add(
            ProjectAlertEvent(
                project_id=project_uuid,
                rule_id=rule_uuid,
                destination_id=destination_uuid,
                event_type=event_type,
                rule_name=job.rule_name,
                metric=job.metric,
                operator=job.operator,
                threshold=job.threshold,
                current_value=job.current_value,
                message=(
                    f"Alert delivery to {job.destination_kind} "
                    f"{'succeeded' if delivered else 'failed'}"
                ),
            )
        )
        if delivered:
            rule = db.query(ProjectAlertRule).filter(ProjectAlertRule.id == rule_uuid).first()
            if rule is not None:
                rule.last_notified_at = now


def _process_job(job: AlertNotificationJob) -> None:
    delivered = False
    for attempt in range(1, settings.alert_notification_max_retries + 1):
        delivered = _post_webhook_json(job)
        if delivered:
            break
        if attempt < settings.alert_notification_max_retries:
            time.sleep(settings.alert_notification_retry_backoff_seconds * attempt)
    _record_job_outcome(job, delivered)


def _worker_loop() -> None:
    while True:
        stop_event = _stop_event
        queue = _queue
        if stop_event is None or queue is None:
            return
        if stop_event.is_set():
            return
        try:
            job = queue.get(timeout=0.5)
        except Empty:
            continue
        try:
            _process_job(job)
        except Exception:
            logger.warning("Unhandled exception in alert notification worker", exc_info=True)
        finally:
            queue.task_done()


def start_alert_notification_dispatcher() -> None:
    """Start background notification dispatcher thread if enabled."""
    if not settings.alert_notification_async_enabled:
        return
    with _lifecycle_lock:
        global _queue, _stop_event, _worker_thread
        if _worker_thread is not None and _worker_thread.is_alive():
            return
        _queue = Queue(maxsize=settings.alert_notification_queue_maxsize)
        _stop_event = threading.Event()
        _worker_thread = threading.Thread(
            target=_worker_loop,
            name="alert-notification-dispatcher",
            daemon=True,
        )
        _worker_thread.start()
        logger.info(
            "Alert notification dispatcher started (queue_maxsize=%d, retries=%d)",
            settings.alert_notification_queue_maxsize,
            settings.alert_notification_max_retries,
        )


def stop_alert_notification_dispatcher(timeout_seconds: float = 5.0) -> None:
    """Stop background notification dispatcher thread."""
    with _lifecycle_lock:
        global _queue, _stop_event, _worker_thread
        stop_event = _stop_event
        worker_thread = _worker_thread
        if stop_event is not None:
            stop_event.set()
    if worker_thread is not None:
        worker_thread.join(timeout=timeout_seconds)
    with _lifecycle_lock:
        _queue = None
        _stop_event = None
        _worker_thread = None


def enqueue_alert_notification_job(job: AlertNotificationJob) -> bool:
    """Enqueue a notification job for asynchronous delivery."""
    queue = _queue
    if queue is None:
        return False
    try:
        queue.put_nowait(job)
        return True
    except Full:
        logger.warning("Alert notification queue is full; dropping notification job")
        return False


def get_alert_notification_queue_size() -> int:
    """Current queue size (mainly for diagnostics/tests)."""
    queue = _queue
    if queue is None:
        return 0
    return queue.qsize()
