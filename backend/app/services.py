from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import InterviewRun, InterviewTurn, Observation, Profile, ResearchSource, SessionRecord, utcnow
from .mimo import DemoMiMoClient, MiMoClient, MiMoError
from .parsing import ResumeParseError, parse_resume
from .prompts import (
    FEEDBACK_SYSTEM,
    FEEDBACK_USER,
    INTERVIEW_SYSTEM,
    INTERVIEW_USER,
    PLAN_SYSTEM,
    PLAN_USER,
    PROFILE_SYSTEM,
    PROFILE_USER,
    REPAIR_SYSTEM,
    RESEARCH_SYSTEM,
    RESEARCH_USER,
)
from .schemas import FeedbackPayload, PlanPayload, ResearchBriefPayload, ResearchSourcePayload


T = TypeVar("T", bound=BaseModel)


class ServiceError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def provider() -> MiMoClient:
    return DemoMiMoClient() if settings.mock_mimo else MiMoClient()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _model_json(client: MiMoClient, system: str, user: str, schema: type[T], *, web_search: bool = False) -> tuple[T, list[dict[str, Any]]]:
    try:
        completion = client.complete(system, user, web_search=web_search)
        return schema.model_validate_json(completion.content), completion.annotations
    except (ValidationError, json.JSONDecodeError) as first_error:
        # A single repair retry keeps malformed model output from corrupting state.
        try:
            repair = client.complete(REPAIR_SYSTEM, f"目标结构：{schema.model_json_schema()}\n原始输出：{getattr(locals().get('completion', None), 'content', '')}", web_search=False)
            return schema.model_validate_json(repair.content), repair.annotations
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
    candidate, _ = _model_json(provider(), PROFILE_SYSTEM, PROFILE_USER.format(resume=resume_text[:50000]), CandidateProfilePayload)
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


def create_plan(db: Session, session: SessionRecord) -> InterviewRun:
    profile = db.get(Profile, session.id)
    if not profile:
        raise ServiceError("请先提交科研方向和简历。", 409)
    if session.status in {"interview_in_progress", "ready_for_feedback"}:
        raise ServiceError("当前面试尚未结束，不能覆盖正在使用的计划。", 409)
    client = provider()
    search_enabled = settings.mimo_web_search_enabled
    try:
        research, annotations = _model_json(client, RESEARCH_SYSTEM, RESEARCH_USER.format(direction=profile.direction, group=profile.target_group, profile=profile.candidate_profile_json), ResearchBriefPayload, web_search=search_enabled)
    except ServiceError:
        if search_enabled:
            # Search plugin failures degrade research, but must not block planning.
            research = ResearchBriefPayload(research_status="degraded", key_conclusions=["联网资料不可用，以下内容未核验。"], uncertainty=["课题组近期方向待确认"], sources=[])
            annotations = []
        else:
            raise
    if not search_enabled:
        # General knowledge cannot be presented as a verified source without a search.
        research.research_status = "degraded"
        research.uncertainty = list(dict.fromkeys([*research.uncertainty, "未启用联网检索，课题组与近期论文信息待核验。"]))
        research.sources = []
    elif annotations:
        # MiMo returns web citations as message annotations. Normalize the
        # provider-specific shape into the stable local source contract.
        for annotation in annotations:
            if hasattr(annotation, "model_dump"):
                annotation = annotation.model_dump()
            if not isinstance(annotation, dict):
                continue
            nested = annotation.get("source") if isinstance(annotation.get("source"), dict) else {}
            url = annotation.get("url") or nested.get("url")
            if not url or any(source.url == url for source in research.sources):
                continue
            research.sources.append(ResearchSourcePayload(title=annotation.get("title") or nested.get("title") or "MiMo web source", url=url, accessed_at=datetime.utcnow().date().isoformat(), conclusion=annotation.get("text") or annotation.get("snippet") or "由 MiMo Web Search 返回，需结合原文核验。", relation="用于定向面试规划", verified=True))
    plan, _ = _model_json(client, PLAN_SYSTEM, PLAN_USER.format(direction=profile.direction, group=profile.target_group, research=research.model_dump_json(), profile=profile.candidate_profile_json), PlanPayload)
    run = InterviewRun(id=secrets.token_urlsafe(18), session_id=session.id, status="ready_for_interview", profile_revision=session.profile_revision, plan_profile_revision=session.profile_revision, research_status=research.research_status, plan_json=plan.model_dump_json(), research_json=research.model_dump_json())
    db.add(run)
    for source in research.sources:
        db.add(ResearchSource(run_id=run.id, title=source.title, url=source.url, accessed_at=source.accessed_at, conclusion=source.conclusion, relation=source.relation, verified=source.verified))
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
    run.status = "interview_in_progress"
    turn = InterviewTurn(run_id=run.id, sequence=1, role="interviewer", content=first.core_question, topic=first.title)
    db.add(turn)
    session.status = "interview_in_progress"
    db.commit()
    return run, first.core_question, first.title, 1


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
    output, _ = _model_json(provider(), INTERVIEW_SYSTEM, INTERVIEW_USER.format(plan=run.plan_json, transcript=transcript[-30000:], answer=answer), InterviewerPayload)
    if answer.strip() in {"跳过", "跳过本题"}:
        output.observation = "候选人主动跳过本题；该轮不作为能力证据。"
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
    feedback, _ = _model_json(provider(), FEEDBACK_SYSTEM, FEEDBACK_USER.format(profile=profile.candidate_profile_json if profile else "{}", plan=run.plan_json, transcript=transcript, observations=observations), FeedbackPayload)
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
