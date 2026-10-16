from pydantic import BaseModel, ConfigDict, Field


class RecommendationResult(BaseModel):
    """Response expected from the external recommender. Extra fields are allowed and stored raw."""

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "examples": [
                {
                    "disease": "late_blight",
                    "confidence": 0.72,
                    "risk_level": "high",
                    "explanation": "Prolonged leaf wetness and several similar reports nearby.",
                    "actions": ["Remove infected leaves", "Contact the extension officer"],
                }
            ]
        },
    )

    disease: str | None = Field(None, description="Predicted disease/problem; null if none identified")
    confidence: float | None = Field(None, ge=0, le=1)
    risk_level: str = Field("unknown", description="low | medium | high | unknown")
    explanation: str | None = None
    actions: list[str] = Field(default_factory=list)
