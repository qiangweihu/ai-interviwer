from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


STATES = {
    "needs_onboarding",
    "ready_for_planning",
    "ready_for_interview",
    "interview_in_progress",
    "ready_for_feedback",
    "complete",
}


class SessionResponse(BaseModel):
    status: str
    profile_revision: int
    plan_profile_revision: int | None = None
    current_run_id: str | None = None
    expires_at: datetime
    profile_complete: bool = False
    plan_preview: dict[str, Any] | None = None


class PlanTopic(BaseModel):
    title: str
    objective: str
    core_question: str
    followups: list[str] = Field(default_factory=list, max_length=3)
    expected_evidence: list[str] = Field(default_factory=list)
    evaluation_dimensions: list[str] = Field(default_factory=list)
    minutes: int = Field(default=2, ge=1, le=10)


class ResearchSourcePayload(BaseModel):
    title: str
    url: str
    accessed_at: str
    conclusion: str
    relation: str
    verified: bool = False


class ResearchBriefPayload(BaseModel):
    research_status: Literal["verified", "degraded"]
    key_conclusions: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    sources: list[ResearchSourcePayload] = Field(default_factory=list)


class PlanPayload(BaseModel):
    duration_minutes: int = Field(default=25, ge=10, le=60)
    main_question_count: int = Field(default=10, ge=8, le=12)
    topics: list[PlanTopic] = Field(min_length=8, max_length=12)

    @model_validator(mode="after")
    def align_question_count(self):
        self.main_question_count = len(self.topics)
        return self


class StartResponse(BaseModel):
    status: str
    question: str
    topic: str | None = None
    turn_sequence: int


class InterviewStateResponse(BaseModel):
    status: str
    question: str | None = None
    topic: str | None = None
    turn_sequence: int | None = None
    turns: list[dict[str, str | int]] = Field(default_factory=list)


class AnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=12000)
    request_id: str = Field(min_length=8, max_length=128)

    @field_validator("answer")
    @classmethod
    def answer_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("回答不能为空")
        return value.strip()


class AnswerResponse(BaseModel):
    status: str
    question: str | None = None
    topic: str | None = None
    turn_sequence: int | None = None
    done: bool = False
    clarification: bool = False


class IssuePayload(BaseModel):
    category: str
    statement: str
    evidence: list[str] = Field(default_factory=list)
    action: str


class RatingPayload(BaseModel):
    score: int = Field(ge=1, le=5)
    evidence: list[str] = Field(default_factory=list)
    confidence: Literal["高", "中", "低"] = "中"


class FeedbackPayload(BaseModel):
    overall: str
    evidence_coverage: str
    confidence: Literal["高", "中", "低"] = "中"
    ratings: dict[str, RatingPayload]
    strengths: list[str] = Field(default_factory=list)
    issues: list[IssuePayload] = Field(default_factory=list)
    improvement_examples: list[str] = Field(default_factory=list)
    priority_drills: list[str] = Field(min_length=3, max_length=3)
    next_round: str


class FeedbackResponse(BaseModel):
    status: str
    feedback: FeedbackPayload
