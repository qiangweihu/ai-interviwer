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


class ResearchBriefPayload(BaseModel):
    # The current MVP deliberately does not perform external retrieval.
    research_status: Literal["degraded"] = "degraded"
    key_conclusions: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)


class PlanPayload(BaseModel):
    duration_minutes: int = Field(default=25, ge=10, le=60)
    main_question_count: int = Field(default=10, ge=8, le=12)
    topics: list[PlanTopic] = Field(min_length=8, max_length=12)

    @model_validator(mode="before")
    @classmethod
    def pad_short_model_output(cls, value: Any):
        """Keep a nearly valid model response usable without inventing CV facts.

        MiMo occasionally returns seven topics even though the contract asks
        for 8–12. Add only generic coverage topics before normal validation;
        these contain no candidate-specific claims and let the interview
        continue while preserving the minimum plan contract.
        """
        if not isinstance(value, dict):
            return value
        topics = value.get("topics")
        if not isinstance(topics, list) or len(topics) >= 8:
            return value

        fallback_topics = [
            {
                "title": "专业基础补充",
                "objective": "补充核验方向相关的核心概念和边界。",
                "core_question": "请解释目标方向中一个尚未展开的核心概念，并说明它的适用边界。",
                "followups": ["这个概念依赖哪些关键假设？"],
                "expected_evidence": ["定义、机制、边界"],
                "evaluation_dimensions": ["专业基础"],
                "minutes": 2,
            },
            {
                "title": "实验设计补充",
                "objective": "补充核验实验设计、指标和对照。",
                "core_question": "如果要验证一个改动确实有效，你会如何设计最小对照实验？",
                "followups": ["结果不符合预期时先检查什么？"],
                "expected_evidence": ["假设、指标、对照"],
                "evaluation_dimensions": ["科研思维"],
                "minutes": 2,
            },
            {
                "title": "方向匹配补充",
                "objective": "补充核验研究动机与方向关联。",
                "core_question": "你希望在这个研究方向中优先解决哪类问题，为什么？",
                "followups": ["你会如何开始验证这个想法？"],
                "expected_evidence": ["具体动机、问题关联"],
                "evaluation_dimensions": ["方向匹配"],
                "minutes": 2,
            },
            {
                "title": "沟通反思补充",
                "objective": "补充核验复盘和清晰表达能力。",
                "core_question": "请回顾一次没有达到预期的尝试，并说明你会如何改进。",
                "followups": ["你如何判断改进是否有效？"],
                "expected_evidence": ["事实、反思、行动"],
                "evaluation_dimensions": ["表达沟通"],
                "minutes": 2,
            },
        ]
        padded = list(topics)
        existing_titles = {
            item.get("title") for item in padded if isinstance(item, dict) and item.get("title")
        }
        for fallback in fallback_topics:
            if len(padded) >= 8:
                break
            topic = dict(fallback)
            title = topic["title"]
            if title in existing_titles:
                title = f"{title}（补充）"
            topic["title"] = title
            padded.append(topic)
            existing_titles.add(title)
        normalized = dict(value)
        normalized["topics"] = padded
        normalized["main_question_count"] = len(padded)
        return normalized

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
