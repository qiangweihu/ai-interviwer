from __future__ import annotations

import hashlib
import json
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
from .schemas import FeedbackPayload, InterviewerStyleSelection, PlanPayload, ResearchBriefPayload


T = TypeVar("T", bound=BaseModel)


class ServiceError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def provider() -> MiMoClient:
    return DemoMiMoClient() if settings.mock_mimo else MiMoClient()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _style_snapshot(raw: Any | None) -> dict[str, Any]:
    """Normalize a stored or requested style to the server-owned snapshot."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = None
    if not isinstance(raw, dict):
        return default_snapshot()
    try:
        canonical = snapshot_for_selection(raw)
        # Stored run/preference records may contain a prompt snapshot. Keep it
        # when present so a later server deployment cannot silently change the
        # behavior of an already prepared round.
        if isinstance(raw.get("prompt_addendum"), str) and raw["prompt_addendum"].strip():
            canonical["prompt_addendum"] = raw["prompt_addendum"]
        if isinstance(raw.get("version"), str) and raw["version"].strip():
            canonical["version"] = raw["version"]
        return canonical
    except ValueError:
        return default_snapshot()


def style_for_session(session: SessionRecord) -> dict[str, Any]:
    return _style_snapshot(session.preferred_interviewer_style_json)


def style_for_run(run: InterviewRun) -> dict[str, Any]:
    return _style_snapshot(run.interviewer_style_json)


def _requested_style(session: SessionRecord, selection: InterviewerStyleSelection | None) -> dict[str, Any]:
    if selection is not None:
        return _style_snapshot(selection.model_dump())
    return style_for_session(session)


def _interview_system(style: dict[str, Any]) -> str:
    return (
        f"{INTERVIEW_SYSTEM}\n\n"
        f"本轮固定面试官类型：{style['name']}\n"
        f"本轮风格行为指令：{style['prompt_addendum']}"
    )


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


def create_plan(db: Session, session: SessionRecord, selection: InterviewerStyleSelection | None = None) -> InterviewRun:
    profile = db.get(Profile, session.id)
    if not profile:
        raise ServiceError("请先提交科研方向和简历。", 409)
    if session.status != "ready_for_planning":
        raise ServiceError("当前阶段不能重新准备面试。请先完成当前面试或开始下一轮。", 409)
    style = _requested_style(session, selection)
    # Save the preference before model calls so a failed preparation can be
    # retried without losing the user's choice.
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
    plan = _model_json(client, PLAN_SYSTEM, PLAN_USER.format(direction=profile.direction, group=profile.target_group, research=research.model_dump_json(), profile=profile.candidate_profile_json), PlanPayload)
    run = InterviewRun(id=secrets.token_urlsafe(18), session_id=session.id, status="ready_for_interview", profile_revision=session.profile_revision, plan_profile_revision=session.profile_revision, research_status=research.research_status, plan_json=plan.model_dump_json(), research_json=research.model_dump_json(), interviewer_style_json=_json(style))
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
    try:
        first_question = _model_json(
            provider(),
            _interview_system(style),
            INTERVIEW_START_USER.format(plan=run.plan_json, topic=first.title),
            InterviewerPayload,
        )
        if first_question.question.strip():
            question = first_question.question.strip()
    except ServiceError:
        # A transient start-time model failure should not prevent a round from
        # starting; the neutral plan question remains a safe fallback.
        pass
    run.status = "interview_in_progress"
    turn = InterviewTurn(run_id=run.id, sequence=1, role="interviewer", content=question, topic=first.title)
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
        payload = InterviewerPayload(question=next_turn.content if next_turn else "", topic=next_turn.topic or "" if next_turn else "", done=next_turn is None)
        return run, payload, next_turn.sequence if next_turn else None
    max_seq = max((t.sequence for t in run.turns), default=0)
    current_question = next((turn for turn in reversed(run.turns) if turn.role == "interviewer"), None)
    current_topic = current_question.topic if current_question else ""
    topic_question_count = sum(
        1 for turn in run.turns if turn.role == "interviewer" and turn.topic == current_topic
    )
    followup_depth = max(0, topic_question_count - 1)
    db.add(InterviewTurn(run_id=run.id, sequence=max_seq + 1, role="candidate", content=answer, request_id=request_id))
    db.flush()
    if answer.strip() in {"结束面试", "结束本轮", "结束"}:
        run.status = "ready_for_feedback"
        session.status = "ready_for_feedback"
        db.add(Observation(run_id=run.id, turn_sequence=max_seq + 1, topic="结束", evidence="候选人主动结束面试。", needs_clarification=False))
        db.commit()
        return run, InterviewerPayload(done=True, topic="结束"), None
    plan = PlanPayload.model_validate_json(run.plan_json or "{}")
    transcript = "\n".join(f"{t.sequence}. {t.role}: {t.content}" for t in run.turns)
    output = _model_json(
        provider(),
        _interview_system(style_for_run(run)),
        INTERVIEW_USER.format(
            plan=run.plan_json,
            transcript=transcript[-30000:],
            answer=answer,
            current_topic=current_topic,
            followup_depth=followup_depth,
        ),
        InterviewerPayload,
    )
    if answer.strip() in {"跳过", "跳过本题"}:
        output.observation = "候选人主动跳过本题；该轮不作为能力证据。"
    if output.next_action == "clarify":
        output.clarification = True
    if output.next_action == "end_interview":
        output.done = True
    interviewer_count = len(db.scalars(select(InterviewTurn).where(InterviewTurn.run_id == run.id, InterviewTurn.role == "interviewer")).all())
    output.done = output.done or interviewer_count >= plan.main_question_count
    if output.done or not output.question.strip():
        output.question = ""
        run.status = "ready_for_feedback"
        session.status = "ready_for_feedback"
        db.add(Observation(run_id=run.id, turn_sequence=max_seq + 1, topic=output.topic, evidence=output.observation or "候选人回答已记录。", needs_clarification=output.clarification))
        db.commit()
        return run, output, None
    next_seq = max_seq + 2
    db.add(InterviewTurn(run_id=run.id, sequence=next_seq, role="interviewer", content=output.question.strip(), topic=output.topic or "动态追问"))
    db.add(Observation(run_id=run.id, turn_sequence=max_seq + 1, topic=output.topic, evidence=output.observation or "候选人回答已记录。", needs_clarification=output.clarification))
    db.commit()
    return run, output, next_seq


def end_interview(db: Session, session: SessionRecord) -> InterviewRun:
    run = get_current_run(db, session)
    if not run or run.status not in {"interview_in_progress", "ready_for_feedback"}:
        raise ServiceError("当前没有可结束的面试。", 409)
    if run.status == "interview_in_progress":
        seq = max((t.sequence for t in run.turns), default=0) + 1
        db.add(InterviewTurn(run_id=run.id, sequence=seq, role="system", content="候选人输入：结束面试", topic="结束"))
        run.status = "ready_for_feedback"
        session.status = "ready_for_feedback"
        db.commit()
    return run


def generate_feedback(db: Session, session: SessionRecord) -> FeedbackPayload:
    run = get_current_run(db, session)
    if not run or run.status not in {"ready_for_feedback", "complete"}:
        raise ServiceError("请先结束一轮面试。", 409)
    if run.feedback_json:
        return FeedbackPayload.model_validate_json(run.feedback_json)
    profile = db.get(Profile, session.id)
    transcript = "\n".join(f"第{t.sequence}轮 {t.role}：{t.content}" for t in run.turns)
    observations = "\n".join(f"第{o.turn_sequence}轮：{o.evidence}" for o in run.observations)
    feedback = _model_json(provider(), FEEDBACK_SYSTEM, FEEDBACK_USER.format(profile=profile.candidate_profile_json if profile else "{}", plan=run.plan_json, transcript=transcript, observations=observations), FeedbackPayload)
    required_dimensions = ["专业基础", "项目深度", "科研思维", "方向匹配", "表达沟通"]
    for dimension in required_dimensions:
        if dimension not in feedback.ratings:
            feedback.ratings[dimension] = {"score": 1, "evidence": ["本轮没有足够的独立证据"], "confidence": "低"}
    feedback.ratings = {dimension: feedback.ratings[dimension] for dimension in required_dimensions}
    if len([turn for turn in run.turns if turn.role == "candidate"]) < 2:
        feedback.confidence = "低"
        feedback.evidence_coverage = f"evidence_limited：{feedback.evidence_coverage}"
    run.feedback_json = feedback.model_dump_json()
    run.status = "complete"
    session.status = "complete"
    db.commit()
    return feedback
