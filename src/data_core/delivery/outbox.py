"""Transactional outbox: webhooks to the dashboard and the phone system.

Events are written in the same transaction as the recommendation, attempted inline right away, and
retried with exponential backoff by POST /internal/tick (cron) if the receiver was unavailable.
"""

import hashlib
import hmac
import json
import logging
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from data_core.config import Settings
from data_core.db.models import Case, CaseStatus, OutboxEvent, OutboxStatus
from data_core.timeutil import as_utc, utcnow

log = logging.getLogger(__name__)


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


MOCK_SCHEME = "mock://"


def enqueue_events(case: Case, payload: dict, settings: Settings, mocked: bool) -> list[OutboxEvent]:
    """`mocked` (config.yaml delivery.mocked): both channels go to mock:// targets that are only logged."""
    if mocked:
        targets = [("dashboard", f"{MOCK_SCHEME}dashboard"), ("phone", f"{MOCK_SCHEME}phone")]
    else:
        targets = []
        if settings.dashboard_webhook_url:
            targets.append(("dashboard", settings.dashboard_webhook_url))
        phone_url = case.request.callback_url or settings.phone_webhook_url
        if phone_url:
            targets.append(("phone", phone_url))

    events = [
        OutboxEvent(channel=channel, target_url=url, event=payload["event"], payload=payload)
        for channel, url in targets
    ]
    case.outbox_events.extend(events)
    return events


def _backoff_s(attempts: int) -> int:
    return min(30 * 2 ** (attempts - 1), 3600)


def send_event(http: httpx.Client, event: OutboxEvent, settings: Settings) -> bool:
    now = utcnow()
    if event.target_url.startswith(MOCK_SCHEME):
        log.info("mock delivery %s -> %s: %s", event.event, event.target_url, event.payload.get("case_id"))
        event.attempts += 1
        event.status = OutboxStatus.SENT
        event.sent_at = now
        event.last_error = None
        return True

    body = json.dumps(event.payload, separators=(",", ":"), ensure_ascii=False).encode()
    headers = {
        "Content-Type": "application/json",
        "X-DataCore-Event": event.event,
        "X-DataCore-Delivery": str(event.id),
    }
    if settings.webhook_secret:
        headers["X-DataCore-Signature"] = sign(settings.webhook_secret, body)

    event.attempts += 1
    try:
        resp = http.post(event.target_url, content=body, headers=headers, timeout=settings.webhook_timeout_s)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        event.last_error = f"{type(exc).__name__}: {exc}"[:1000]
        if event.attempts >= settings.webhook_max_attempts:
            event.status = OutboxStatus.FAILED
            log.error("webhook %s to %s failed permanently: %s", event.id, event.target_url, exc)
        else:
            event.next_attempt_at = now + timedelta(seconds=_backoff_s(event.attempts))
            log.warning("webhook %s to %s failed (attempt %d): %s", event.id, event.target_url, event.attempts, exc)
        return False

    event.status = OutboxStatus.SENT
    event.sent_at = now
    event.last_error = None
    return True


def refresh_case_status(case: Case) -> None:
    if case.status == CaseStatus.RECOMMENDED and all(e.status == OutboxStatus.SENT for e in case.outbox_events):
        case.status = CaseStatus.DELIVERED


def deliver_case(session: Session, case: Case, http: httpx.Client, settings: Settings) -> None:
    now = utcnow()
    for event in case.outbox_events:
        if event.status == OutboxStatus.PENDING and as_utc(event.next_attempt_at) <= now:
            send_event(http, event, settings)
    refresh_case_status(case)
    session.commit()


def deliver_due(session: Session, http: httpx.Client, settings: Settings, limit: int = 100) -> dict[str, int]:
    events = session.scalars(
        select(OutboxEvent)
        .where(OutboxEvent.status == OutboxStatus.PENDING, OutboxEvent.next_attempt_at <= utcnow())
        .order_by(OutboxEvent.id)
        .limit(limit)
    ).all()
    sent = sum(send_event(http, event, settings) for event in events)
    for case in {event.case for event in events}:
        refresh_case_status(case)
    session.commit()
    return {"attempted": len(events), "sent": sent}
