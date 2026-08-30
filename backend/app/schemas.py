from __future__ import annotations

import json
import re
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


TaskType = Literal["oral", "coding", "code_review", "practical"]
PracticalType = Literal["sql", "experiment_analysis"]
Language = Literal["python", "cpp", "sql", "text"]


class PublicSample(BaseModel):
    """A visible, data-only example for an executable task.

    Tests are deliberately represented as input/output data.  The server owns
    the harness and never executes a model-generated test script.
    """

    input: str = ""
    output: str = ""
    explanation: str = ""
    rows: list[list[Any]] | None = None

    @model_validator(mode="after")
    def validate_size(self):
        for value in (self.input, self.output, self.explanation):
            if len(str(value).encode("utf-8")) > 16384:
                raise ValueError("公开样例数据超过大小限制")
        if self.rows is not None:
            if len(self.rows) > 200 or any(len(row) > 50 for row in self.rows):
                raise ValueError("公开样例行数超过大小限制")
        return self


def _coerce_string_list(value: Any) -> Any:
    """Accept the common model shorthand ``"one item"`` for a string list.

    Planning models occasionally emit one string where the JSON contract asks
    for an array of strings. Normalize that shape before Pydantic validates the
    task, while preserving non-string values so normal validation still reports
    genuinely malformed data.
    """

    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        # A model may have serialized an array as a JSON string. Prefer that
        # interpretation when it is unambiguous.
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, list):
            return decoded
        parts = [part.strip(" \t\r\n-•") for part in re.split(r"[\n,，、;；]+", text)]
        return [part for part in parts if part]
    if isinstance(value, (tuple, set)):
        return list(value)
    return value


class PlanTopic(BaseModel):
    """A backwards-compatible oral topic or a structured practical task."""

    model_config = ConfigDict(extra="ignore")

    title: str
    objective: str
    core_question: str
    followups: list[str] = Field(default_factory=list, max_length=3)
    expected_evidence: list[str] = Field(default_factory=list)
    evaluation_dimensions: list[str] = Field(default_factory=list)
    minutes: int = Field(default=2, ge=1, le=15)
    constraints: list[str] = Field(default_factory=list, max_length=20)
    task_id: str | None = Field(default=None, max_length=128)
    type: TaskType = "oral"
    practical_type: PracticalType | None = None
    language_options: list[Language] = Field(default_factory=list, max_length=3)
    starter_code: str = Field(default="", max_length=65536)
    materials: dict[str, Any] = Field(default_factory=dict)
    public_samples: list[PublicSample] = Field(default_factory=list, max_length=10)
    # The following fields are private plan data.  They are persisted with the
    # run but stripped by all public response builders.
    hidden_tests: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    reference_solution: str = Field(default="", max_length=65536)
    reference_language: Language | None = None
    rubric: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="before")
    @classmethod
    def normalize_list_shorthand(cls, value: Any):
        if not isinstance(value, Mapping):
            return value
        normalized = dict(value)
        for field in ("followups", "expected_evidence", "evaluation_dimensions", "constraints", "language_options", "rubric"):
            if field in normalized:
                normalized[field] = _coerce_string_list(normalized[field])

        # Models sometimes place the broad task kind in ``practical_type``
        # (for example ``practical_type: coding``). Accept the shorthand and
        # move it to the canonical ``type``/``practical_type`` pair before
        # Literal validation rejects an otherwise usable plan.
        type_aliases = {
            "code": "coding",
            "programming": "coding",
            "编程": "coding",
            "debugging": "code_review",
            "debug": "code_review",
            "调试": "code_review",
            "sqlite": "sql",
            "实验分析": "experiment_analysis",
            "experiment": "experiment_analysis",
            "analysis": "experiment_analysis",
        }
        raw_type = normalized.get("type")
        raw_practical_type = normalized.get("practical_type")
        canonical_type = type_aliases.get(str(raw_type).strip().lower(), raw_type) if raw_type is not None else raw_type
        canonical_practical_type = type_aliases.get(str(raw_practical_type).strip().lower(), raw_practical_type) if raw_practical_type is not None else raw_practical_type
        if canonical_practical_type == "coding":
            normalized["type"] = "coding"
            normalized["practical_type"] = None
        elif canonical_practical_type == "code_review":
            normalized["type"] = "code_review"
            normalized["practical_type"] = None
        elif canonical_practical_type in {"sql", "experiment_analysis"}:
            normalized["type"] = "practical"
            normalized["practical_type"] = canonical_practical_type
        else:
            if canonical_type is not None:
                normalized["type"] = canonical_type
            else:
                normalized.pop("type", None)
            if canonical_practical_type is not None:
                normalized["practical_type"] = canonical_practical_type
        return normalized

    @model_validator(mode="after")
    def normalize_task(self):
        if self.type == "oral":
            self.practical_type = None
            self.language_options = []
            self.starter_code = ""
            self.public_samples = []
            self.hidden_tests = []
            self.reference_solution = ""
            self.reference_language = None
            self.rubric = []
        elif self.type == "coding":
            self.practical_type = None
            if not self.language_options:
                self.language_options = ["python", "cpp"]
            if any(language not in {"python", "cpp"} for language in self.language_options):
                raise ValueError("编程题只能选择 Python 或 C++")
        elif self.type == "code_review":
            self.practical_type = None
            if not self.language_options:
                self.language_options = ["python", "cpp"]
            if any(language not in {"python", "cpp"} for language in self.language_options):
                raise ValueError("代码理解题只能选择 Python 或 C++")
        elif self.type == "practical" and self.practical_type == "sql":
            self.language_options = ["sql"]
        elif self.type == "practical" and self.practical_type is None:
            self.practical_type = "experiment_analysis"
            self.language_options = ["text"]
        elif self.type == "practical" and self.practical_type == "experiment_analysis":
            self.language_options = ["text"]
        if self.reference_language and self.reference_language not in self.language_options:
            raise ValueError("参考解法语言必须属于该题的语言选项")
        allowed_test_keys = {"input", "output", "rows"}
        for test in self.hidden_tests:
            if not isinstance(test, dict) or any(key not in allowed_test_keys for key in test):
                raise ValueError("隐藏测试只能包含 input、output 或 rows 数据字段")
            for key in ("input", "output"):
                if key in test and len(str(test[key]).encode("utf-8")) > 16384:
                    raise ValueError("测试数据超过大小限制")
            if "rows" in test and (
                not isinstance(test["rows"], list)
                or len(test["rows"]) > 200
                or any(not isinstance(row, list) or len(row) > 50 for row in test["rows"])
            ):
                raise ValueError("隐藏测试结果行数超过大小限制")
        return self


# Newer callers can use the more descriptive name without breaking existing
# imports in tests and integrations.
PlanItem = PlanTopic


class SessionResponse(BaseModel):
    status: str
    profile_revision: int
    plan_profile_revision: int | None = None
    current_run_id: str | None = None
    expires_at: datetime
    profile_complete: bool = False
    plan_preview: dict[str, Any] | None = None
    interviewer_style: InterviewerStylePublic | None = None


class ResearchBriefPayload(BaseModel):
    # The current MVP deliberately does not perform external retrieval.
    research_status: Literal["degraded"] = "degraded"
    key_conclusions: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)


class PlanPayload(BaseModel):
    plan_version: int = Field(default=2, ge=1, le=2)
    duration_minutes: int = Field(default=35, ge=10, le=60)
    main_question_count: int = Field(default=8, ge=7, le=10)
    topics: list[PlanTopic] = Field(min_length=7, max_length=10)

    @model_validator(mode="before")
    @classmethod
    def pad_short_model_output(cls, value: Any):
        """Keep a nearly valid model response usable without inventing CV facts.

        MiMo occasionally returns fewer than eight topics even though the
        normal mixed-plan target is 7–10. Add only generic coverage topics before normal validation;
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
        while len(padded) < 7:
            padded.append(
                {
                    "title": f"基础补充（{len(padded) + 1}）",
                    "objective": "补充核验方向相关的核心概念。",
                    "core_question": "请解释一个与你目标方向相关的核心概念，并说明它的适用边界。",
                    "followups": [],
                    "expected_evidence": ["定义、机制、边界"],
                    "evaluation_dimensions": ["专业知识与基础"],
                    "minutes": 2,
                    "type": "oral",
                }
            )
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
    task: dict[str, Any] | None = None


class InterviewStateResponse(BaseModel):
    status: str
    question: str | None = None
    topic: str | None = None
    turn_sequence: int | None = None
    turns: list[dict[str, Any]] = Field(default_factory=list)
    task: dict[str, Any] | None = None


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
    task: dict[str, Any] | None = None


class PracticalRunRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)
    language: Language
    source: str = Field(default="", max_length=65536)
    explanation: str = Field(default="", max_length=12000)
    analysis: dict[str, str] | None = None

    @field_validator("source")
    @classmethod
    def source_is_string(cls, value: str) -> str:
        return value

    @model_validator(mode="after")
    def require_source_or_analysis(self):
        if not self.source.strip() and not self.analysis and not self.explanation.strip():
            raise ValueError("代码、SQL、解释或结构化分析不能为空")
        if self.analysis:
            allowed = {"judgment", "evidence", "next_validation"}
            if set(self.analysis) - allowed:
                raise ValueError("分析字段只能包含 judgment、evidence、next_validation")
            if any(len(value.encode("utf-8")) > 12000 for value in self.analysis.values()):
                raise ValueError("分析内容超过大小限制")
        return self

    def effective_source(self) -> str:
        """Return the source payload used by the runner and evidence store."""

        if self.source.strip():
            return self.source
        if self.analysis is not None:
            return json.dumps(self.analysis, ensure_ascii=False, separators=(",", ":"))
        # Explanation-only code-review submissions intentionally have no
        # executable source. Keep the empty value so the service records
        # ``not_executed`` instead of accidentally running the string "{}".
        return ""


class PracticalRunResponse(BaseModel):
    status: Literal["ok", "failed", "unavailable", "not_executed"]
    task_id: str
    passed: int = 0
    total: int = 0
    compile_error: str | None = None
    runtime_error: str | None = None
    output_truncated: bool = False
    execution_ms: int | None = None
    public: bool = True


class PracticalSubmitResponse(BaseModel):
    status: str
    task_id: str
    locked: bool = True
    result: PracticalRunResponse
    question: str | None = None
    topic: str | None = None
    turn_sequence: int | None = None
    done: bool = False
    clarification: bool = False
    task: dict[str, Any] | None = None


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
