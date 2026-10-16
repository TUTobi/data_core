"""Export the integration contracts as JSON Schema into contracts/schemas/.

    python scripts/export_schemas.py

Share these with the other workstreams (phone/Telegram input, Raspberry Pi, recommender, dashboard).
"""

import json
from pathlib import Path

from data_core.schemas.context import DecisionContext
from data_core.schemas.recommendation import RecommendationResult
from data_core.schemas.requests import CallerRequestIn
from data_core.schemas.sensors import SensorReadingBatch, SensorReadingIn
from data_core.schemas.webhooks import WebhookPayload

CONTRACTS = {
    # who sends -> data-core
    "caller_request.in": (CallerRequestIn, "validation"),
    "sensor_reading.in": (SensorReadingIn, "validation"),
    "sensor_reading_batch.in": (SensorReadingBatch, "validation"),
    # data-core -> recommender -> data-core
    "decision_context.to_recommender": (DecisionContext, "serialization"),
    "recommendation.from_recommender": (RecommendationResult, "validation"),
    # data-core -> dashboard / phone system
    "webhook.case_recommended": (WebhookPayload, "serialization"),
}


def main() -> None:
    out_dir = Path(__file__).resolve().parent.parent / "contracts" / "schemas"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, (model, mode) in CONTRACTS.items():
        path = out_dir / f"{name}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(mode=mode), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote", path.relative_to(out_dir.parent.parent))


if __name__ == "__main__":
    main()
