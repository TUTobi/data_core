from typing import Protocol

from data_core.schemas.context import DecisionContext
from data_core.schemas.recommendation import RecommendationResult


class RecommenderClient(Protocol):
    """Gateway to the (external, out-of-scope) recommendation system."""

    name: str

    def recommend(self, context: DecisionContext) -> RecommendationResult: ...
