"""Mock of the external recommender service.

    uvicorn mocks.mock_recommender:app --port 8001

Implements the contract the core expects: POST /predict with a DecisionContext -> RecommendationResult.
The recommendation team can replace this 1:1 with their real service.
"""

from fastapi import FastAPI

from data_core.recommender.mock import MockRecommender
from data_core.schemas.context import DecisionContext
from data_core.schemas.recommendation import RecommendationResult

app = FastAPI(title="Mock recommender")
_model = MockRecommender()


@app.post("/predict", response_model=RecommendationResult)
def predict(context: DecisionContext) -> RecommendationResult:
    return _model.recommend(context)
