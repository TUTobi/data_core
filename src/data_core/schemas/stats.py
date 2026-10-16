from pydantic import BaseModel, Field

from data_core.schemas.common import UtcDatetime


class ProblemCount(BaseModel):
    problem_type: str | None = Field(description="Reported problem category (null = not classified)")
    count: int


class StatsSummary(BaseModel):
    since: UtcDatetime
    days: int
    total_calls: int
    distinct_callers: int = Field(description="Distinct caller_ref values; calls without caller_ref are not counted")
    repeat_callers: int = Field(description="Callers with more than one call in the window")
    problems: list[ProblemCount] = Field(description="Reported problems, most frequent first")
