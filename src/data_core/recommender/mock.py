from data_core.schemas.context import DecisionContext
from data_core.schemas.recommendation import RecommendationResult


class MockRecommender:
    """Stand-in for the external recommender - NOT a disease model.

    Crude humidity/rain/cluster rules so the pipeline can be demoed end-to-end before the
    recommendation team's service exists.
    """

    name = "mock"

    def recommend(self, context: DecisionContext) -> RecommendationResult:
        ev = context.evidence
        score = 0
        reasons: list[str] = []

        weather = ev.weather
        if weather and weather.past.hours_rh_ge_90 is not None and weather.past.hours_rh_ge_90 >= 12:
            score += 2
            reasons.append(f"{weather.past.hours_rh_ge_90} h with humidity >= 90 % in the last {weather.past.hours} h")
        if weather and (weather.past.precipitation_mm or 0) >= 20:
            score += 1
            reasons.append(f"{weather.past.precipitation_mm} mm rain in the last {weather.past.hours} h")

        humid_sensors = [s for s in ev.sensors if s.metric.startswith("humidity") and s.mean >= 85]
        if humid_sensors:
            score += 1
            s = humid_sensors[0]
            reasons.append(f"field sensor {s.sensor_id} reports mean humidity {s.mean} % ({s.distance_km} km away)")

        history = ev.caller_history
        if history and history.same_problem_count >= 3:
            score += 1
            reasons.append(f"{history.same_problem_count} similar reports within {history.radius_km:g} km")

        has_evidence = bool(weather or ev.sensors or history)
        if not has_evidence:
            risk = "unknown"
        elif score >= 3:
            risk = "high"
        elif score >= 2:
            risk = "medium"
        else:
            risk = "low"

        suspected = score >= 2
        actions = (
            [
                "Inspect leaves for spots, mould or lesions and remove affected plant parts",
                "Avoid overhead irrigation and improve air flow between plants",
                "Contact the agricultural extension officer for confirmation and treatment advice",
            ]
            if suspected
            else ["Monitor the crop over the next days and call again if symptoms spread"]
        )
        return RecommendationResult(
            disease="suspected_fungal_disease" if suspected else None,
            confidence=round(min(0.3 + 0.15 * score, 0.9), 2),
            risk_level=risk,
            explanation="[MOCK RECOMMENDER] " + ("; ".join(reasons) if reasons else "no strong risk indicators found"),
            actions=actions,
            model="mock-heuristic-v0",
        )
