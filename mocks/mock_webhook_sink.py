"""Mock receiver for the dashboard / phone-system webhooks.

    WEBHOOK_SECRET=dev-secret uvicorn mocks.mock_webhook_sink:app --port 8002

POST /hooks/{channel} stores the payload (and checks the HMAC signature if WEBHOOK_SECRET is set);
GET /received lists everything received so far.
"""

import hmac
import json
import os
from datetime import UTC, datetime

from fastapi import FastAPI, Request

from data_core.delivery.outbox import sign

app = FastAPI(title="Mock webhook sink")
SECRET = os.environ.get("WEBHOOK_SECRET", "")
RECEIVED: list[dict] = []


@app.post("/hooks/{channel}")
async def receive(channel: str, request: Request) -> dict:
    body = await request.body()
    signature = request.headers.get("x-datacore-signature")
    valid = None
    if SECRET:
        valid = signature is not None and hmac.compare_digest(signature, sign(SECRET, body))
    entry = {
        "channel": channel,
        "received_at": datetime.now(UTC).isoformat(),
        "signature_valid": valid,
        "payload": json.loads(body),
    }
    RECEIVED.append(entry)
    rec = entry["payload"].get("recommendation", {})
    print(f"[{channel}] case={entry['payload'].get('case_id')} risk={rec.get('risk_level')} signature_valid={valid}")
    return {"ok": True}


@app.get("/received")
def received() -> list[dict]:
    return RECEIVED
