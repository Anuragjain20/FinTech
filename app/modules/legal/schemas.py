from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Issue(BaseModel):
    severity: Literal["high", "medium", "low"]
    issue: str = Field(min_length=1, max_length=2000)
    citations: list[str] = Field(default_factory=list)
    suggestion: str = ""

    @field_validator("severity", mode="before")
    @classmethod
    def _lower(cls, v):
        return v.strip().lower() if isinstance(v, str) else v


class ClauseAnalysis(BaseModel):
    issues: list[Issue] = Field(default_factory=list, max_length=10)


class Verdict(BaseModel):
    supported: bool
    reason: str = ""
