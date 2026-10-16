import httpx

from data_core.schemas.context import DecisionContext
from data_core.schemas.recommendation import RecommendationResult


class HttpRecommender:
    """POSTs the DecisionContext as JSON to RECOMMENDER_URL and expects a RecommendationResult back."""

    name = "http"

    def __init__(self, http: httpx.Client, url: str, timeout_s: float, api_key: str = ""):
        if not url:
            raise ValueError("RECOMMENDER_URL must be set when RECOMMENDER_MODE=http")
        self.http = http
        self.url = url
        self.timeout_s = timeout_s
        self.api_key = api_key

    def recommend(self, context: DecisionContext) -> RecommendationResult:
        headers = {"X-API-Key": self.api_key} if self.api_key else {}
        resp = self.http.post(
            self.url, json=context.model_dump(mode="json"), headers=headers, timeout=self.timeout_s
        )
        resp.raise_for_status()
        return RecommendationResult.model_validate(resp.json())
