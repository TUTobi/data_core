from typing import Literal

from pydantic import BaseModel, Field

from data_core.schemas.common import UtcDatetime
from data_core.schemas.recommendation import RecommendationResult
from data_core.schemas.requests import Location


class WebhookPayload(BaseModel):
    """Body POSTed to the dashboard and the phone system once a recommendation exists.

    Headers: X-DataCore-Event, X-DataCore-Delivery and (if a secret is configured)
    X-DataCore-Signature: sha256=<hex HMAC-SHA256 of the raw body>.
    """

    event: Literal["case.recommended"] = "case.recommended"
    case_id: str
    request_id: str
    external_id: str | None
    channel: str
    caller_ref: str | None
    problem_type: str | None
    location: Location | None
    recommendation: RecommendationResult
    evidence_summary: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: UtcDatetime
