from __future__ import annotations

import hashlib
import json
import math
import secrets
from datetime import timedelta
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import InterviewRun, InterviewTurn, Observation, Profile, SessionRecord, utcnow
from .interviewer_styles import default_snapshot, snapshot_for_selection
from .mimo import DemoMiMoClient, MiMoClient, MiMoError
from .parsing import ResumeParseError, parse_resume
from .prompts import (
    FEEDBACK_SYSTEM,
    FEEDBACK_USER,
    INTERVIEW_SYSTEM,
    INTERVIEW_START_USER,
    INTERVIEW_USER,
    PLAN_SYSTEM,
    PLAN_USER,
    PROFILE_SYSTEM,
    PROFILE_USER,
    REPAIR_SYSTEM,
    RESEARCH_SYSTEM,
    RESEARCH_USER,
)
from .schemas import FeedbackAssessmentPayload, FeedbackDimensionAssessment, FeedbackPayload, PlanPayload, ResearchBriefPayload


T = TypeVar("T", bound=BaseModel)


# The model supplies evidence-backed dimension assessments, but the public
# probability is always calculated here with this fixed, reviewable rubric.
FEEDBACK_DIMENSION_WEIGHTS: dict[str, float] = {
    "专业知识与基础": 0.30,
    "项目与科研经历深度": 0.25,
    "科研思维": 0.25,
    "方向匹配": 0.10,
    "面试表达与应答": 0.10,
}
FEEDBACK_CONFIDENCE_FACTORS: dict[str, float] = {"高": 1.0, "中": 0.75, "低": 0.5}
FEEDBACK_DIMENSION_ALIASES: dict[str, str] = {
    "专业基础": "专业知识与基础",
    "项目深度": "项目与科研经历深度",
    "表达沟通": "面试表达与应答",
}


class ServiceError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def provider() -> MiMoClient:
    return DemoMiMoClient() if settings.mock_mimo else MiMoClient()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _style_snapshot(raw: Any | None, *, fallback_to_default: bool = True) -> dict[str, Any]:
    """Resolve stored/requested style data to a server-owned snapshot."""

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = None
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    if not isinstance(raw, dict):
        return default_snapshot()
    try:
        snapshot = snapshot_for_selection(raw)
    except ValueError:
        if not fallback_to_default:
            raise
        return default_snapshot()

    # Preserve the exact server-generated snapshot on an existing run. This
    # keeps an in-progress round stable if a later deployment edits the style
    # catalog (including its follow-up guardrails). Values submitted by the
    # client are never copied into these fields without passing through
    # snapshot_for_selection above.
    for key in ("version", "preset_id", "name", "summary", "prompt_addendum", "planner_addendum"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            snapshot[key] = value
    if isinstance(raw.get("traits"), list) and all(isinstance(item, str) for item in raw["traits"]):
        snapshot["traits"] = list(raw["traits"])
    if isinstance(raw.get("policy"), dict):
        snapshot["policy"] = dict(raw["policy"])
    return snapshot


def style_for_session(session: SessionRecord) -> dict[str, Any]:
    return _style_snapshot(session.preferred_interviewer_style_json)


def style_for_run(run: InterviewRun) -> dict[str, Any]:
    return _style_snapshot(run.interviewer_style_json)


def _requested_style(session: SessionRecord, selection: Any | None) -> dict[str, Any]:
    if selection is not None:
        try:
            return _style_snapshot(selection, fallback_to_default=False)
        except ValueError as exc:
            raise ServiceError("无效的面试官风格组合。", 422) from exc
    return style_for_session(session)


def _interviewer_system(style: dict[str, Any]) -> str:
    return (
        f"{INTERVIEW_SYSTEM}\n\n"
        f"本轮固定面试官风格：{style['name']}\n"
        f"风格行为规则：{style['prompt_addendum']}"
    )


def _topic_index_for_turn(turn: InterviewTurn, plan: PlanPayload) -> int | None:
    if turn.plan_topic_index is not None and 0 <= turn.plan_topic_index < len(plan.topics):
        return turn.plan_topic_index
    if turn.topic:
        for index, topic in enumerate(plan.topics):
            if topic.title == turn.topic:
                return index
    return None


def _covered_topic_indices(run: InterviewRun, plan: PlanPayload) -> set[int]:
    covered: set[int] = set()
    for turn in run.turns:
        if turn.role != "interviewer":
            continue
        index = _topic_index_for_turn(turn, plan)
        if index is not None:
            covered.add(index)
    return covered


def _first_uncovered_topic(plan: PlanPayload, covered: set[int]) -> int | None:
    return next((index for index in range(len(plan.topics)) if index not in covered), None)


def _model_json(client: MiMoClient, system: str, user: str, schema: type[T]) -> T:
    try:
        completion = client.complete(system, user)
        return schema.model_validate_json(completion.content)
    except (ValidationError, json.JSONDecodeError) as first_error:
        # A single repair retry keeps malformed model output from corrupting state.
        try:
            repair = client.complete(REPAIR_SYSTEM, f"目标结构：{schema.model_json_schema()}\n原始输出：{getattr(locals().get('completion', None), 'content', '')}")
            return schema.model_validate_json(repair.content)
        except Exception as second_error:
            raise ServiceError(f"模型返回格式不可用，请稍后重试：{second_error}", 502) from first_error
    except MiMoError as exc:
        raise ServiceError(str(exc), 503) from exc


def _feedback_probability(assessment: FeedbackAssessmentPayload, candidate_turn_count: int) -> int:
    """Convert evidence assessments into one calibrated, deterministic value."""

    scores: dict[str, FeedbackDimensionAssessment] = {}
    for raw_name, item in assessment.dimension_scores.items():
        name = FEEDBACK_DIMENSION_ALIASES.get(raw_name, raw_name)
        if name in FEEDBACK_DIMENSION_WEIGHTS and name not in scores:
            scores[name] = item

    weighted_score = 0.0
    confidence = 0.0
    for name, weight in FEEDBACK_DIMENSION_WEIGHTS.items():
        item = scores.get(name)
        if item is None:
            item = FeedbackDimensionAssessment(
                score=50,
                evidence=["本轮没有足够的独立证据"],
                confidence="低",
            )
        weighted_score += item.score * weight
        confidence += FEEDBACK_CONFIDENCE_FACTORS[item.confidence] * weight

    # The logistic curve makes 65 the neutral interview-pass point while
    # keeping very weak/strong evidence from jumping straight to 0%/100%.
    raw_probability = 100 / (1 + math.exp(-(weighted_score - 65) / 10))
    confidence_factor = min(confidence, FEEDBACK_CONFIDENCE_FACTORS[assessment.confidence])
    if candidate_turn_count < 2:
        confidence_factor = min(confidence_factor, FEEDBACK_CONFIDENCE_FACTORS["低"])
    probability = 50 + (raw_probability - 50) * confidence_factor
    return max(5, min(95, int(round(probability))))


def _normalise_feedback_assessment(assessment: FeedbackAssessmentPayload, candidate_turn_count: int) -> FeedbackPayload:
    coverage = assessment.evidence_coverage.strip() or "基于本轮转录和候选人档案。"
    confidence = assessment.confidence
    if candidate_turn_count < 2:
        confidence = "低"
        if not coverage.startswith("evidence_limited"):
            coverage = f"evidence_limited：{coverage}"
    return FeedbackPayload(
        interview_pass_probability=_feedback_probability(assessment, candidate_turn_count),
        overall=assessment.overall.strip() or "本轮反馈仅覆盖已经提供的回答证据。",
        evidence_coverage=coverage,
        confidence=confidence,
        strengths=assessment.strengths,
        professional_knowledge_gaps=assessment.professional_knowledge_gaps,
        interview_skill_gaps=assessment.interview_skill_gaps,
        improvement_examples=assessment.improvement_examples,
        priority_drills=assessment.priority_drills,
        next_round=assessment.next_round,
    )


class CandidateProfilePayload(BaseModel):
    education: str
    courses: list[str]
    projects: list[dict[str, Any]]
    research: list[str]
    skills: list[str]
    achievements: list[str]
    interests: list[str]
    weak_points: list[str]


class InterviewerPayload(BaseModel):
    question: str = ""
    topic: str = ""
    topic_index: int | None = None
    done: bool = False
    clarification: bool = False
    observation: str = ""
    next_action: Literal["follow_up", "next_topic", "clarify", "end_interview"] = "next_topic"


def new_session(db: Session) -> tuple[SessionRecord, str]:
    raw_token = secrets.token_urlsafe(32)
    now = utcnow()
    record = SessionRecord(
        id=secrets.token_urlsafe(18),
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        status="needs_onboarding",
        expires_at=now + timedelta(hours=settings.session_ttl_hours),
    )
    db.add(record)
    db.commit()
    return record, raw_token


def profile_from_upload(db: Session, session: SessionRecord, direction: str, group: str, program: str, filename: str, content: bytes) -> Profile:
    direction = direction.strip()
    if not direction:
        raise ServiceError("请填写具体科研方向。")
    try:
        resume_text = parse_resume(filename, content, settings.max_resume_bytes)
    except ResumeParseError as exc:
        raise ServiceError(str(exc), 422) from exc
    candidate = _model_json(provider(), PROFILE_SYSTEM, PROFILE_USER.format(resume=resume_text[:50000]), CandidateProfilePayload)
    # Preserve historical runs, but make every plan tied to the previous profile
    # revision unusable and visibly expired.
    old_runs = db.scalars(select(InterviewRun).where(InterviewRun.session_id == session.id, InterviewRun.status.in_(["ready_for_interview", "interview_in_progress", "ready_for_feedback"]))).all()
    for old_run in old_runs:
        old_run.status = "expired"
    session.profile_revision += 1
    session.status = "ready_for_planning"
    session.current_run_id = None
    profile = db.get(Profile, session.id)
    if profile is None:
        profile = Profile(session_id=session.id, direction=direction, target_group=group.strip() or "待确认", target_program=program.strip() or "待确认", research_context_json=_json({"direction": direction, "target_group": group.strip() or "待确认", "target_program": program.strip() or "待确认"}), candidate_profile_json=candidate.model_dump_json())
        db.add(profile)
    else:
        profile.direction = direction
        profile.target_group = group.strip() or "待确认"
        profile.target_program = program.strip() or "待确认"
        profile.research_context_json = _json({"direction": direction, "target_group": profile.target_group, "target_program": profile.target_program})
        profile.candidate_profile_json = candidate.model_dump_json()
    db.commit()
    return profile


def create_plan(db: Session, session: SessionRecord, selection: Any | None = None) -> InterviewRun:
    profile = db.get(Profile, session.id)
    if not profile:
        raise ServiceError("请先提交科研方向和简历。", 409)
    if session.status != "ready_for_planning":
        raise ServiceError("当前阶段不能重新准备面试。请先完成当前面试或开始下一轮。", 409)
    style = _requested_style(session, selection)
    # Persist the preference before model calls so a failed preparation can be
    # safely retried without losing the user's choice.
    session.preferred_interviewer_style_json = _json(style)
    db.commit()
    client = provider()
    try:
        research = _model_json(client, RESEARCH_SYSTEM, RESEARCH_USER.format(direction=profile.direction, group=profile.target_group, profile=profile.candidate_profile_json), ResearchBriefPayload)
    except ServiceError:
        # General-knowledge research is optional context and must not block a
        # complete interview plan when the model is temporarily unavailable.
        research = ResearchBriefPayload(
            research_status="degraded",
            key_conclusions=["本轮未获取到额外研究资料，以下内容未联网核验。"],
            uncertainty=["目标课题组近期方向待核验"],
        )
    research.research_status = "degraded"
    research.uncertainty = list(dict.fromkeys([*research.uncertainty, "本轮仅使用通用知识，未进行联网检索。"]))
    plan = _model_json(
        client,
        PLAN_SYSTEM,
        PLAN_USER.format(
            direction=profile.direction,
            group=profile.target_group,
            research=research.model_dump_json(),
            profile=profile.candidate_profile_json,
            style=style["planner_addendum"],
        ),
        PlanPayload,
    )
    run = InterviewRun(
        id=secrets.token_urlsafe(18),
        session_id=session.id,
        status="ready_for_interview",
        profile_revision=session.profile_revision,
        plan_profile_revision=session.profile_revision,
        research_status=research.research_status,
        plan_json=plan.model_dump_json(),
        research_json=research.model_dump_json(),
        interviewer_style_json=_json(style),
    )
    db.add(run)
    session.current_run_id = run.id
    session.status = "ready_for_interview"
    db.commit()
    return run


def get_current_run(db: Session, session: SessionRecord) -> InterviewRun | None:
    return db.get(InterviewRun, session.current_run_id) if session.current_run_id else None


def start_new_round(db: Session, session: SessionRecord) -> None:
    if not db.get(Profile, session.id):
        raise ServiceError("请先提交科研方向和简历。", 409)
    if session.status not in {"complete", "ready_for_feedback"}:
        raise ServiceError("请先完成或结束当前面试，再开始下一轮。", 409)
    session.current_run_id = None
    session.status = "ready_for_planning"
    db.commit()


def start_interview(db: Session, session: SessionRecord) -> tuple[InterviewRun, str, str, int]:
    run = get_current_run(db, session)
    if not run or run.status != "ready_for_interview" or run.plan_profile_revision != session.profile_revision:
        raise ServiceError("当前没有有效的面试计划，请重新规划。", 409)
    plan = PlanPayload.model_validate_json(run.plan_json or "{}")
    first = plan.topics[0]
    style = style_for_run(run)
    question = first.core_question
    # Give the selected style one chance to shape the opening question too.
    # A temporary model failure must not prevent the round from starting: the
    # validated plan question is a safe fallback.
    try:
        first_question = _model_json(
            provider(),
            _interviewer_system(style),
            INTERVIEW_START_USER.format(plan=run.plan_json, topic=first.title),
            InterviewerPayload,
        )
        if first_question.question.strip():
            question = first_question.question.strip()
    except ServiceError:
        pass
    run.status = "interview_in_progress"
    turn = InterviewTurn(
        run_id=run.id,
        sequence=1,
        role="interviewer",
        content=question,
        topic=first.title,
        plan_topic_index=0,
    )
    db.add(turn)
    session.status = "interview_in_progress"
    db.commit()
    return run, question, first.title, 1


def answer_interview(db: Session, session: SessionRecord, answer: str, request_id: str) -> tuple[InterviewRun, InterviewerPayload, int | None]:
    run = get_current_run(db, session)
    if not run or run.status != "interview_in_progress":
        raise ServiceError("当前不在进行中的面试。", 409)
    existing = db.scalar(select(InterviewTurn).where(InterviewTurn.run_id == run.id, InterviewTurn.request_id == request_id))
    if existing:
        next_turn = db.scalar(select(InterviewTurn).where(InterviewTurn.run_id == run.id, InterviewTurn.sequence == existing.sequence + 1, InterviewTurn.role == "interviewer"))
        payload = InterviewerPayload(
            question=next_turn.content if next_turn else "",
            topic=next_turn.topic or "" if next_turn else "",
            topic_index=next_turn.plan_topic_index if next_turn else None,
            done=next_turn is None,
        )
        return run, payload, next_turn.sequence if next_turn else None
    plan = PlanPayload.model_validate_json(run.plan_json or "{}")
    style = style_for_run(run)
    max_seq = max((t.sequence for t in run.turns), default=0)
    current_question = next((turn for turn in reversed(run.turns) if turn.role == "interviewer"), None)
    current_topic = current_question.topic if current_question else ""
    current_topic_index = _topic_index_for_turn(current_question, plan) if current_question else None
    topic_question_count = sum(
        1
        for turn in run.turns
        if turn.role == "interviewer"
        and (
            _topic_index_for_turn(turn, plan) == current_topic_index
            if current_topic_index is not None
            else turn.topic == current_topic
        )
    )
    followup_depth = max(0, topic_question_count - 1)
    interviewer_turns = [turn for turn in run.turns if turn.role == "interviewer"]
    interviewer_count = len(interviewer_turns)
    covered = _covered_topic_indices(run, plan)
    remaining = [index for index in range(len(plan.topics)) if index not in covered]
    followups_used = max(0, interviewer_count - len(covered))
    policy = style["policy"]
    max_followups_total = int(policy["max_followups_total"])
    max_questions = len(plan.topics) + max_followups_total
    db.add(
        InterviewTurn(
            run_id=run.id,
            sequence=max_seq + 1,
            role="candidate",
            content=answer,
            request_id=request_id,
            plan_topic_index=current_topic_index,
        )
    )
    db.flush()
    if answer.strip() in {"结束面试", "结束本轮", "结束"}:
        run.status = "ready_for_feedback"
        session.status = "ready_for_feedback"
        db.add(Observation(run_id=run.id, turn_sequence=max_seq + 1, topic="结束", evidence="候选人主动结束面试。", needs_clarification=False))
        db.commit()
        return run, InterviewerPayload(done=True, topic="结束"), None
    transcript = "\n".join(f"{t.sequence}. {t.role}: {t.content}" for t in run.turns)
    output = _model_json(
        provider(),
        _interviewer_system(style),
        INTERVIEW_USER.format(
            plan=run.plan_json,
            transcript=transcript[-30000:],
            answer=answer,
            current_topic=current_topic,
            followup_depth=followup_depth,
            current_topic_index=current_topic_index if current_topic_index is not None else "未知",
            covered_topics=", ".join(str(index) for index in sorted(covered)) or "无",
            remaining_topics=", ".join(str(index) for index in remaining) or "无",
            max_followups_per_topic=policy["max_followups_per_topic"],
            max_followups_total=max_followups_total,
            topic_order=policy["topic_order"],
        ),
        InterviewerPayload,
    )
    if answer.strip() in {"跳过", "跳过本题"}:
        output.next_action = "next_topic"
        output.observation = "候选人主动跳过本题；该轮不作为能力证据。"
    output.clarification = output.next_action == "clarify"

    # Reserve enough slots for every still-uncovered planned topic. This
    # prevents a deep dive from exhausting the round before core coverage.
    slots_left = max_questions - interviewer_count
    followup_allowed = (
        current_topic_index is not None
        and followup_depth < int(policy["max_followups_per_topic"])
        and followups_used < max_followups_total
        and slots_left > len(remaining)
    )
    requested_index = output.topic_index
    target_index: int | None = None
    if output.next_action in {"follow_up", "clarify"} and followup_allowed:
        target_index = current_topic_index
    elif output.next_action == "next_topic" or not followup_allowed:
        if policy["topic_order"] == "sequential":
            target_index = _first_uncovered_topic(plan, covered)
        elif requested_index in remaining:
            target_index = requested_index
        else:
            target_index = _first_uncovered_topic(plan, covered)
        output.next_action = "next_topic"
        output.clarification = False
    elif output.next_action == "end_interview" and not remaining:
        target_index = None
    else:
        # A model-requested end cannot skip uncovered planned topics.
        target_index = _first_uncovered_topic(plan, covered)
        output.next_action = "next_topic"
        output.clarification = False

    reached_hard_cap = interviewer_count >= max_questions
    if not remaining or reached_hard_cap:
        output.done = True
        target_index = None
    elif target_index is None:
        target_index = _first_uncovered_topic(plan, covered)
        output.next_action = "next_topic"
        output.done = target_index is None
    else:
        # Ignore a premature model `done` flag while planned topics remain.
        output.done = False

    if output.done or target_index is None:
        output.question = ""
        run.status = "ready_for_feedback"
        session.status = "ready_for_feedback"
        db.add(
            Observation(
                run_id=run.id,
                turn_sequence=max_seq + 1,
                topic=current_topic,
                evidence=output.observation or "候选人回答已记录。",
                needs_clarification=output.clarification,
            )
        )
        db.commit()
        return run, output, None
    target_topic = plan.topics[target_index]
    output.topic_index = target_index
    output.topic = target_topic.title
    if not output.question.strip():
        output.question = target_topic.core_question
    if output.next_action == "next_topic" and target_index == current_topic_index:
        output.question = target_topic.core_question
    next_seq = max_seq + 2
    db.add(
        InterviewTurn(
            run_id=run.id,
            sequence=next_seq,
            role="interviewer",
            content=output.question.strip(),
            topic=target_topic.title,
            plan_topic_index=target_index,
        )
    )
    db.add(
        Observation(
            run_id=run.id,
            turn_sequence=max_seq + 1,
            topic=target_topic.title,
            evidence=output.observation or "候选人回答已记录。",
            needs_clarification=output.clarification,
        )
    )
    db.commit()
    return run, output, next_seq


def end_interview(db: Session, session: SessionRecord) -> InterviewRun:
    run = get_current_run(db, session)
    if not run or run.status not in {"interview_in_progress", "ready_for_feedback"}:
        raise ServiceError("当前没有可结束的面试。", 409)
    if run.status == "interview_in_progress":
        seq = max((t.sequence for t in run.turns), default=0) + 1
        db.add(InterviewTurn(run_id=run.id, sequence=seq, role="system", content="候选人输入：结束面试", topic="结束", plan_topic_index=None))
        run.status = "ready_for_feedback"
        session.status = "ready_for_feedback"
        db.commit()
    return run


def generate_feedback(db: Session, session: SessionRecord) -> FeedbackPayload:
    run = get_current_run(db, session)
    if not run or run.status not in {"ready_for_feedback", "complete"}:
        raise ServiceError("请先结束一轮面试。", 409)
    if run.feedback_json:
        # A deployment may still have a cached v1 five-point payload.  Do not
        # expose or numerically convert that legacy result; regenerate from
        # the stored transcript using the v2 evidence contract below.
        try:
            cached = json.loads(run.feedback_json)
            if isinstance(cached, dict) and "ratings" not in cached:
                return FeedbackPayload.model_validate(cached)
        except (ValidationError, json.JSONDecodeError):
            pass
    profile = db.get(Profile, session.id)
    transcript = "\n".join(f"第{t.sequence}轮 {t.role}：{t.content}" for t in run.turns)
    observations = "\n".join(f"第{o.turn_sequence}轮：{o.evidence}" for o in run.observations)
    assessment = _model_json(
        provider(),
        FEEDBACK_SYSTEM,
        FEEDBACK_USER.format(
            profile=profile.candidate_profile_json if profile else "{}",
            plan=run.plan_json,
            transcript=transcript,
            observations=observations,
        ),
        FeedbackAssessmentPayload,
    )
    candidate_turn_count = len([turn for turn in run.turns if turn.role == "candidate"])
    feedback = _normalise_feedback_assessment(assessment, candidate_turn_count)
    run.feedback_json = feedback.model_dump_json()
    run.status = "complete"
    session.status = "complete"
    db.commit()
    return feedback
