from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


STATES = {
    "needs_onboarding",
    "ready_for_planning",
    "ready_for_interview",
    "interview_in_progress",
    "ready_for_feedback",
    "complete",
}


class InterviewerStyleSelection(BaseModel):
    """The only style values accepted from the client.

    ``control``/``plan_adherence`` were the names in the first server
    prototype. Normalize them here so an old browser can be upgraded without
    silently falling back to the default style.
    """

    model_config = ConfigDict(extra="forbid")

    initiative: Literal["leading", "listening"] = "leading"
    tone: Literal["strict", "friendly"] = "friendly"
    structure: Literal["structured", "adaptive"] = "structured"

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_keys(cls, value: Any):
        if not isinstance(value, Mapping):
            return value
        normalized = dict(value)
        if "control" in normalized:
            control = normalized.pop("control")
            mapped = {"dominant": "leading", "listener": "listening"}.get(control, control) if isinstance(control, str) else control
            if "initiative" in normalized and normalized["initiative"] != mapped:
                raise ValueError("面试官风格的对话控制字段冲突。")
            normalized["initiative"] = mapped
        if "plan_adherence" in normalized:
            adherence = normalized.pop("plan_adherence")
            mapped = {"flexible": "adaptive"}.get(adherence, adherence) if isinstance(adherence, str) else adherence
            if "structure" in normalized and normalized["structure"] != mapped:
                raise ValueError("面试官风格的流程字段冲突。")
            normalized["structure"] = mapped
        return normalized


class InterviewerStylePublic(InterviewerStyleSelection):
    version: str
    name: str
    summary: str
    traits: list[str] = Field(default_factory=list)
    preset_id: str = "guided_interviewer"
    # Read-only compatibility fields included in responses. Requests should
    # continue using InterviewerStyleSelection and cannot provide these.
    control: Literal["dominant", "listener"] | None = None
    plan_adherence: Literal["structured", "flexible"] | None = None

    @model_validator(mode="after")
    def populate_legacy_fields(self):
        self.control = "dominant" if self.initiative == "leading" else "listener"
        self.plan_adherence = "flexible" if self.structure == "adaptive" else "structured"
        return self


class InterviewerStyleCatalog(BaseModel):
    version: str
    default_preset_id: str = "guided_interviewer"
    default_selection: InterviewerStyleSelection
    dimensions: dict[str, Any]
    presets: list[InterviewerStylePublic] = Field(default_factory=list)


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interviewer_style: InterviewerStyleSelection | None = None


class SessionResponse(BaseModel):
    status: str
    profile_revision: int
    plan_profile_revision: int | None = None
    current_run_id: str | None = None
    expires_at: datetime
    profile_complete: bool = False
    plan_preview: dict[str, Any] | None = None
    interviewer_style: InterviewerStylePublic | None = None


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
                "evaluation_dimensions": ["专业知识与基础"],
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
                "evaluation_dimensions": ["面试表达与应答"],
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


class TranscriptionResponse(BaseModel):
    text: str


class SpeechConfigResponse(BaseModel):
    enabled: bool
    max_audio_bytes: int
    max_audio_seconds: int
    accepted_types: list[str]


class IssuePayload(BaseModel):
    category: str
    statement: str
    evidence: list[str] = Field(default_factory=list)
    action: str


class FeedbackDimensionAssessment(BaseModel):
    """Internal evidence assessment used to calculate the public probability.

    These values are never returned by the API.  Keeping them separate from
    ``FeedbackPayload`` prevents the UI from accidentally exposing another
    competing score alongside the single probability.
    """

    score: int = Field(ge=0, le=100)
    evidence: list[str] = Field(default_factory=list)
    confidence: Literal["高", "中", "低"] = "中"


class FeedbackAssessmentPayload(BaseModel):
    """Model response contract before deterministic probability calculation."""

    overall: str
    evidence_coverage: str
    confidence: Literal["高", "中", "低"] = "中"
    dimension_scores: dict[str, FeedbackDimensionAssessment] = Field(default_factory=dict)
    strengths: list[str] = Field(default_factory=list)
    professional_knowledge_gaps: list[IssuePayload] = Field(default_factory=list)
    interview_skill_gaps: list[IssuePayload] = Field(default_factory=list)
    improvement_examples: list[str] = Field(default_factory=list)
    priority_drills: list[str] = Field(min_length=3, max_length=3)
    next_round: str


class FeedbackPayload(BaseModel):
    """Public feedback contract: one probability, then evidence-based text."""

    feedback_version: Literal["2"] = "2"
    interview_pass_probability: int = Field(ge=5, le=95)
    overall: str
    evidence_coverage: str
    confidence: Literal["高", "中", "低"] = "中"
    strengths: list[str] = Field(default_factory=list)
    professional_knowledge_gaps: list[IssuePayload] = Field(default_factory=list)
    interview_skill_gaps: list[IssuePayload] = Field(default_factory=list)
    improvement_examples: list[str] = Field(default_factory=list)
    priority_drills: list[str] = Field(min_length=3, max_length=3)
    next_round: str


class FeedbackResponse(BaseModel):
    status: str
    feedback: FeedbackPayload
