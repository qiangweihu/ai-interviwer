from __future__ import annotations

import hashlib
import json
import math
import secrets
from datetime import timedelta
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .db import InterviewRun, InterviewTurn, Observation, PracticalSubmission, Profile, SessionRecord, utcnow
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
from .schemas import FeedbackAssessmentPayload, FeedbackDimensionAssessment, FeedbackPayload, PlanPayload, PlanTopic, ResearchBriefPayload
from .runner import ExecutionResult, RunnerError, runner_client


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


def _task_id(index: int, topic: Any) -> str:
    """Return a stable, non-secret id for a task within one plan."""

    explicit = getattr(topic, "task_id", None)
    return str(explicit or f"task-{index + 1}")


_PRIVATE_TASK_FIELDS = {
    "hidden_tests",
    "reference_solution",
    "reference_language",
    "rubric",
    "solution",
    "answer_key",
    "private_tests",
}


def _topic_public_dict(topic: Any, index: int) -> dict[str, Any]:
    """Build the public task shape used by both the API and model prompts."""

    if hasattr(topic, "model_dump"):
        raw = topic.model_dump()
    elif isinstance(topic, dict):
        raw = dict(topic)
    else:
        raw = {}
    for key in _PRIVATE_TASK_FIELDS:
        raw.pop(key, None)
    if isinstance(raw.get("materials"), dict):
        raw["materials"] = {
            key: value
            for key, value in raw["materials"].items()
            if not any(marker in str(key).lower() for marker in ("hidden", "reference", "rubric", "answer_key", "private", "secret"))
        }
    raw["id"] = _task_id(index, topic)
    raw["type"] = raw.get("type") or "oral"
    return raw


def _public_plan_json(plan_json: str | None) -> str:
    """Remove hidden task contracts before sending a plan to any model."""

    if not plan_json:
        return "{}"
    try:
        plan = PlanPayload.model_validate_json(plan_json)
        raw = plan.model_dump()
        raw["topics"] = [_topic_public_dict(topic, index) for index, topic in enumerate(plan.topics)]
    except (ValidationError, json.JSONDecodeError, TypeError):
        try:
            raw = json.loads(plan_json)
        except (json.JSONDecodeError, TypeError):
            return "{}"
        if isinstance(raw, dict) and isinstance(raw.get("topics"), list):
            raw["topics"] = [_topic_public_dict(topic, index) for index, topic in enumerate(raw["topics"])]
    return _json(raw)


def _task_public(topic: Any, index: int, *, submission: PracticalSubmission | None = None) -> dict[str, Any]:
    """Strip private tests, reference solutions and rubrics before API output."""

    raw = _topic_public_dict(topic, index)
    raw["locked"] = bool(submission.locked) if submission else False
    if submission:
        try:
            result = json.loads(submission.result_json)
        except json.JSONDecodeError:
            result = {}
        raw["submission"] = {
            "language": submission.language,
            "locked": submission.locked,
            "result": {key: result.get(key) for key in ("status", "passed", "total", "compile_error", "runtime_error", "output_truncated", "execution_ms")},
        }
    return raw


def task_for_turn(run: InterviewRun, turn: InterviewTurn | None = None) -> dict[str, Any] | None:
    if not run.plan_json:
        return None
    try:
        plan = PlanPayload.model_validate_json(run.plan_json)
    except ValidationError:
        return None
    current = turn or next((item for item in reversed(run.turns) if item.role == "interviewer"), None)
    if current is None:
        return None
    index = _topic_index_for_turn(current, plan)
    if index is None:
        return None
    topic = plan.topics[index]
    submission = None
    task_id = _task_id(index, topic)
    for candidate in reversed(run.practical_submissions):
        if candidate.task_id == task_id and candidate.locked:
            submission = candidate
            break
    return _task_public(topic, index, submission=submission)


def task_for_index(run: InterviewRun, index: int | None) -> dict[str, Any] | None:
    if index is None or not run.plan_json:
        return None
    try:
        plan = PlanPayload.model_validate_json(run.plan_json)
    except ValidationError:
        return None
    if index < 0 or index >= len(plan.topics):
        return None
    topic = plan.topics[index]
    submission = next((item for item in reversed(run.practical_submissions) if item.task_id == _task_id(index, topic) and item.locked), None)
    return _task_public(topic, index, submission=submission)


def _normalise_plan(plan: PlanPayload) -> PlanPayload:
    """Fill task ids and ensure task metadata is internally consistent."""

    used_ids: set[str] = set()
    for index, topic in enumerate(plan.topics):
        candidate_id = str(topic.task_id or f"task-{index + 1}")
        if candidate_id in used_ids:
            candidate_id = f"task-{index + 1}"
            suffix = 2
            while candidate_id in used_ids:
                candidate_id = f"task-{index + 1}-{suffix}"
                suffix += 1
        topic.task_id = candidate_id
        used_ids.add(candidate_id)
        if topic.type in {"coding", "code_review"} and not topic.language_options:
            topic.language_options = ["python", "cpp"]
    plan.plan_version = 2
    plan.duration_minutes = max(35, plan.duration_minutes)
    return plan


def _as_oral(topic: PlanTopic) -> PlanTopic:
    """Downgrade an unavailable practical task to a usable oral prompt."""

    topic.type = "oral"
    topic.practical_type = None
    topic.language_options = []
    topic.starter_code = ""
    topic.materials = {}
    topic.public_samples = []
    topic.hidden_tests = []
    topic.reference_solution = ""
    topic.reference_language = None
    topic.rubric = []
    if any(marker in topic.core_question for marker in ("编辑器", "代码", "SQL", "查询", "提交修正版")):
        topic.core_question = f"请口头说明：{topic.objective} 你会如何分析并验证自己的判断？"
    return topic


def _fallback_oral_topic(title: str = "综合基础补充") -> PlanTopic:
    return PlanTopic.model_validate(
        {
            "title": title,
            "objective": "补充核验方向相关基础概念。",
            "core_question": "请解释一个与你目标方向相关的核心概念，并说明它的适用边界。",
            "followups": [],
            "expected_evidence": ["定义、机制、边界"],
            "evaluation_dimensions": ["专业知识与基础"],
            "minutes": 2,
            "type": "oral",
        }
    )


def _is_executable_task(topic: PlanTopic) -> bool:
    if topic.type == "coding":
        return bool(topic.reference_solution and topic.public_samples and topic.hidden_tests)
    if topic.type == "practical" and topic.practical_type == "sql":
        return bool(topic.reference_solution and topic.public_samples and topic.hidden_tests)
    if topic.type == "code_review":
        return bool(topic.reference_solution and topic.public_samples and topic.hidden_tests)
    return False


def _fallback_coding_task() -> dict[str, Any]:
    return {
        "title": "算法实现实操",
        "objective": "检查把问题拆解为可执行算法并处理边界条件的能力。",
        "core_question": "请在编辑器中完成题目，并说明你的复杂度判断。",
        "followups": ["如果输入规模扩大，你会如何优化？"],
        "expected_evidence": ["可运行代码、边界处理、复杂度说明"],
        "evaluation_dimensions": ["专业知识与基础", "科研思维"],
        "minutes": 10,
        "constraints": ["第一行给出 n，第二行给出 n 个整数", "n 可为 0，结果输出一个整数"],
        "type": "coding",
        "language_options": ["python", "cpp"],
        "starter_code": "# 读取标准输入并将结果写到标准输出\n",
        "public_samples": [{"input": "4\n1 2 3 4\n", "output": "10\n", "explanation": "求整数序列的和。"}],
        "hidden_tests": [{"input": "0\n\n", "output": "0\n"}, {"input": "3\n-1 5 2\n", "output": "6\n"}],
        "reference_solution": "import sys\ndata=list(map(int,sys.stdin.read().split())); print(sum(data[1:]) if data else 0)",
        "reference_language": "python",
        "rubric": ["正确处理空输入和负数", "输出符合要求", "能解释复杂度"],
    }


def _fallback_code_review_task() -> dict[str, Any]:
    return {
        "title": "代码理解与调试",
        "objective": "检查定位逻辑错误、解释执行过程和提出修复方案的能力。",
        "core_question": "请指出下面代码在边界输入下的问题，说明原因并提交修正版（可选）。",
        "followups": ["你会用什么最小测试先复现？"],
        "expected_evidence": ["问题定位、反例、修复理由"],
        "evaluation_dimensions": ["专业知识与基础", "科研思维"],
        "minutes": 8,
        "constraints": ["解释空输入与单元素输入", "修正版使用标准输入/输出"],
        "type": "code_review",
        "language_options": ["python"],
        "starter_code": "import sys\nvalues = list(map(float, sys.stdin.read().split()))\nprint(sum(values) / (len(values) - 1))\n",
        "materials": {"prompt": "解释空输入和单元素输入的行为，指出分母问题，并在愿意时提交 stdin/stdout 修正版。"},
        "public_samples": [{"input": "2 4\n", "output": "3.0\n", "explanation": "两个数的平均值。"}],
        "hidden_tests": [{"input": "2 4\n", "output": "3.0\n"}, {"input": "1\n", "output": "1.0\n"}],
        "reference_solution": "import sys\nvalues = list(map(float, sys.stdin.read().split()))\nif not values: print(0.0)\nelse: print(sum(values) / len(values))\n",
        "reference_language": "python",
        "rubric": ["指出 len(values)-1 的错误", "给出空输入处理", "解释最小复现用例"],
    }


def _ensure_practical_topics(plan: PlanPayload) -> PlanPayload:
    """Repair a model response that ignored the mixed-interview contract."""

    if not settings.practical_runner_enabled:
        # During a staged rollout, do not expose an executable task that cannot
        # be submitted. Keep the same question as a text-only oral prompt.
        for item in plan.topics:
            if item.type != "oral":
                _as_oral(item)
        return _normalise_plan(plan)

    topics = list(plan.topics)
    if not any(_is_executable_task(item) for item in topics):
        # Preserve up to six high-signal oral topics and replace unusable
        # practical items with generic, verifiable tasks. No CV facts are
        # invented by this repair path.
        manual_analysis = next(
            (item for item in topics if item.type == "practical" and item.practical_type == "experiment_analysis"),
            None,
        )
        selected: list[PlanTopic] = [item for item in topics if item.type == "oral"][:6]
        for item in topics:
            if len(selected) >= 6:
                break
            if item is not manual_analysis and item not in selected:
                selected.append(_as_oral(item))
        topics = selected
        if manual_analysis is not None:
            topics.append(manual_analysis)
        topics.append(PlanTopic.model_validate(_fallback_coding_task()))
        if len(topics) < 8:
            topics.append(PlanTopic.model_validate(_fallback_code_review_task()))

    # Keep the mixed-round contract bounded even if a model overproduces
    # practical tasks. The first two remain practical; extras become clear
    # oral prompts so the core oral coverage is not displaced.
    practical_seen = 0
    for item in topics:
        if item.type == "oral":
            continue
        practical_seen += 1
        if practical_seen > 2:
            _as_oral(item)

    while sum(item.type == "oral" for item in topics) < 6 and len(topics) < 10:
        topics.append(_fallback_oral_topic(f"综合基础补充（{len(topics) + 1}）"))
    normalized = PlanPayload.model_validate({"plan_version": 2, "duration_minutes": 35, "main_question_count": len(topics), "topics": [item.model_dump() for item in topics]})
    return _normalise_plan(normalized)


def _validate_practical_plan(plan: PlanPayload) -> None:
    if not settings.practical_runner_enabled:
        # Rollout flag off: oral-only planning remains available and safe.
        return
    if not runner_client.health():
        raise ServiceError("实操题执行器暂时不可用，请稍后重试。", 503)
    if not any(_is_executable_task(item) for item in plan.topics):
        raise ServiceError("本次计划没有可由执行器验证的实操题。", 502)
    for topic in plan.topics:
        if topic.type not in {"coding", "code_review", "practical"}:
            continue
        if topic.type == "practical" and topic.practical_type == "experiment_analysis":
            if not topic.materials or not topic.rubric:
                raise ServiceError(f"实验分析题“{topic.title}”缺少材料或评价契约。", 502)
            continue
        if topic.type == "code_review" and not topic.hidden_tests:
            # Explanation-only reviews are valid; a corrected program is
            # executed only when the planner supplied data-only tests.
            continue
        if not topic.public_samples or not topic.hidden_tests:
            raise ServiceError(f"实操题“{topic.title}”缺少公开或隐藏测试。", 502)
        for sample in topic.public_samples:
            if topic.type == "practical" and topic.practical_type == "sql":
                if sample.rows is None and not sample.output:
                    raise ServiceError(f"SQL 题“{topic.title}”的公开样例缺少预期行。", 502)
            elif sample.rows is not None:
                raise ServiceError(f"代码题“{topic.title}”的样例必须是标准输出数据。", 502)
        for test in topic.hidden_tests:
            if topic.type == "practical" and topic.practical_type == "sql":
                if "rows" not in test and "output" not in test:
                    raise ServiceError(f"SQL 题“{topic.title}”的隐藏测试缺少预期行。", 502)
            elif "output" not in test or "rows" in test:
                raise ServiceError(f"代码题“{topic.title}”的隐藏测试格式不可用。", 502)
        if not topic.reference_solution:
            raise ServiceError(f"实操题“{topic.title}”缺少可验证的参考解法。", 502)
        language = topic.reference_language or (topic.language_options or ["python"])[0]
        source = topic.reference_solution
        for hidden in (False, True):
            try:
                result = runner_client.execute(topic.model_dump(), source, language, hidden=hidden)
            except RunnerError as exc:
                raise ServiceError(str(exc), 503) from exc
            if result.status != "ok" or result.passed != result.total:
                visibility = "隐藏" if hidden else "公开"
                raise ServiceError(f"实操题“{topic.title}”的{visibility}测试契约未通过，已拒绝本次计划。", 502)


def _repair_or_regenerate_plan(
    client: MiMoClient,
    failed_plan: PlanPayload,
    *,
    direction: str,
    group: str,
    research: ResearchBriefPayload,
    profile: str,
    style: str,
) -> PlanPayload | None:
    """Give the planner one repair attempt, then one fresh generation attempt.

    Runner failures are intentionally not repaired here: an unavailable
    executor must remain a visible 503 rather than silently becoming a text
    question or a model guess.
    """

    repair_user = (
        "原计划的实操题预检未通过。请只修复题面、数据测试、参考解法或评价契约，"
        "不要虚构候选人经历，并返回完整计划 JSON。\n"
        f"原计划：{failed_plan.model_dump_json()}"
    )
    try:
        repaired = _model_json(client, REPAIR_SYSTEM, repair_user, PlanPayload)
        repaired = _ensure_practical_topics(repaired)
        _validate_practical_plan(repaired)
        return repaired
    except ServiceError as exc:
        if exc.status_code == 503:
            raise
        pass

    try:
        regenerated = _model_json(
            client,
            PLAN_SYSTEM,
            PLAN_USER.format(
                direction=direction,
                group=group,
                research=research.model_dump_json(),
                profile=profile,
                style=style,
            ),
            PlanPayload,
        )
        regenerated = _ensure_practical_topics(regenerated)
        _validate_practical_plan(regenerated)
        return regenerated
    except ServiceError as exc:
        if exc.status_code == 503:
            raise
        return None


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
    plan = _ensure_practical_topics(plan)
    try:
        _validate_practical_plan(plan)
    except ServiceError as exc:
        if exc.status_code != 502:
            raise
        repaired = _repair_or_regenerate_plan(
            client,
            plan,
            direction=profile.direction,
            group=profile.target_group,
            research=research,
            profile=profile.candidate_profile_json,
            style=style["planner_addendum"],
        )
        if repaired is None:
            raise exc
        plan = repaired
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
    if settings.practical_runner_enabled and any(item.type in {"coding", "code_review"} or (item.type == "practical" and item.practical_type == "sql") for item in plan.topics):
        if not runner_client.health():
            raise ServiceError("实操题执行器暂时不可用，请稍后重试。", 503)
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
            INTERVIEW_START_USER.format(plan=_public_plan_json(run.plan_json), topic=first.title),
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
        turn_kind=first.type,
        task_id=_task_id(0, first) if first.type != "oral" else None,
    )
    db.add(turn)
    session.status = "interview_in_progress"
    db.commit()
    return run, question, first.title, 1


def answer_interview(
    db: Session,
    session: SessionRecord,
    answer: str,
    request_id: str,
    *,
    turn_kind: str = "oral",
    task_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    force_next_topic: bool = False,
) -> tuple[InterviewRun, InterviewerPayload, int | None]:
    run = get_current_run(db, session)
    if not run:
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
    if run.status != "interview_in_progress":
        raise ServiceError("当前不在进行中的面试。", 409)
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
            turn_kind=turn_kind,
            task_id=task_id,
            metadata_json=_json(metadata) if metadata else None,
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
            plan=_public_plan_json(run.plan_json),
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
    if force_next_topic:
        # A confirmed practical submission locks the task and must advance;
        # the interviewer may not turn a final code result into another edit
        # loop on the same task.
        output.next_action = "next_topic"
        output.topic_index = None
        output.clarification = False

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
            turn_kind=target_topic.type,
            task_id=_task_id(target_index, target_topic) if target_topic.type != "oral" else None,
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


_practical_trial_cache: dict[tuple[str, str, str], ExecutionResult] = {}
_practical_trial_counts: dict[tuple[str, str], int] = {}


def _execution_from_json(raw_json: str) -> ExecutionResult:
    try:
        raw = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        raw = {}
    defaults = ExecutionResult()
    values = {
        field: raw.get(field, getattr(defaults, field))
        for field in ExecutionResult.__dataclass_fields__
    }
    return ExecutionResult(**values)


def _validate_analysis_source(source: str) -> None:
    try:
        payload = json.loads(source)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ServiceError("实验分析必须提交结构化判断、依据和下一步验证方案。", 422) from exc
    if not isinstance(payload, dict) or any(not str(payload.get(key, "")).strip() for key in ("judgment", "evidence", "next_validation")):
        raise ServiceError("实验分析必须完整填写判断、依据和下一步验证方案。", 422)


def _current_practical_topic(run: InterviewRun, task_id: str) -> tuple[PlanPayload, int, Any, InterviewTurn]:
    if not run.plan_json:
        raise ServiceError("当前面试没有可用计划。", 409)
    try:
        plan = PlanPayload.model_validate_json(run.plan_json)
    except ValidationError as exc:
        raise ServiceError("当前面试计划格式不可用。", 409) from exc
    current = next((turn for turn in reversed(run.turns) if turn.role == "interviewer"), None)
    if not current:
        raise ServiceError("当前没有待作答题目。", 409)
    index = _topic_index_for_turn(current, plan)
    if index is None:
        raise ServiceError("当前题目无法定位。", 409)
    topic = plan.topics[index]
    if topic.type not in {"coding", "code_review", "practical"}:
        raise ServiceError("当前题目不是实操题，请使用普通回答入口。", 409)
    expected_id = _task_id(index, topic)
    if expected_id != task_id:
        raise ServiceError("只能提交当前正在进行的实操题。", 409)
    return plan, index, topic, current


def run_practical_task(db: Session, session: SessionRecord, task_id: str, source: str, language: str, request_id: str) -> ExecutionResult:
    run = get_current_run(db, session)
    if not run:
        raise ServiceError("当前不在进行中的面试。", 409)
    cache_key = (run.id, task_id, request_id)
    if cache_key in _practical_trial_cache:
        return _practical_trial_cache[cache_key]
    stored_trial = db.scalar(
        select(PracticalSubmission).where(
            PracticalSubmission.run_id == run.id,
            PracticalSubmission.task_id == task_id,
            PracticalSubmission.request_id == request_id,
            PracticalSubmission.is_final.is_(False),
        )
    )
    if stored_trial:
        result = _execution_from_json(stored_trial.result_json)
        _practical_trial_cache[cache_key] = result
        return result
    if run.status != "interview_in_progress":
        raise ServiceError("当前不在进行中的面试。", 409)
    _plan, index, topic, _current = _current_practical_topic(run, task_id)
    if language not in topic.language_options and not (topic.type == "practical" and topic.practical_type == "experiment_analysis" and language == "text"):
        raise ServiceError("当前实操题不支持该语言。", 422)
    if len(source.encode("utf-8")) > settings.practical_max_source_chars:
        raise ServiceError("代码或回答超过大小限制。", 422)
    if not source.strip() and topic.type != "code_review" and not (topic.type == "practical" and topic.practical_type == "experiment_analysis"):
        raise ServiceError("代码或 SQL 不能为空。", 422)
    if topic.type == "practical" and topic.practical_type == "experiment_analysis":
        _validate_analysis_source(source)
    count_key = (run.id, task_id)
    persisted_count = db.scalar(
        select(func.count()).select_from(PracticalSubmission).where(
            PracticalSubmission.run_id == run.id,
            PracticalSubmission.task_id == task_id,
            PracticalSubmission.is_final.is_(False),
        )
    ) or 0
    trial_count = max(_practical_trial_counts.get(count_key, 0), int(persisted_count))
    if trial_count >= settings.practical_max_runs_per_task:
        raise ServiceError("本题公开试跑次数已达到上限。", 429)
    if topic.type == "practical" and topic.practical_type == "experiment_analysis":
        result = ExecutionResult(status="ok", passed=1, total=1, public=True)
    elif topic.type == "code_review" and not source.strip():
        raise ServiceError("公开试跑需要先提交修正版代码。", 422)
    else:
        try:
            result = runner_client.execute(topic.model_dump(), source, language, hidden=False)
        except RunnerError as exc:
            raise ServiceError(str(exc), 503) from exc
    _practical_trial_counts[count_key] = trial_count + 1
    # Public trials retain only an idempotency key, count and execution
    # summary. The source column is deliberately empty for non-final rows.
    db.add(
        PracticalSubmission(
            run_id=run.id,
            task_id=task_id,
            turn_sequence=max((turn.sequence for turn in run.turns), default=0),
            task_type=topic.type if topic.type != "practical" else (topic.practical_type or topic.type),
            language=language,
            source="",
            result_json=_json(result.as_dict()),
            is_final=False,
            locked=False,
            request_id=request_id,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raced = db.scalar(
            select(PracticalSubmission).where(
                PracticalSubmission.run_id == run.id,
                PracticalSubmission.task_id == task_id,
                PracticalSubmission.request_id == request_id,
                PracticalSubmission.is_final.is_(False),
            )
        )
        if raced:
            result = _execution_from_json(raced.result_json)
        else:
            raise ServiceError("公开试跑记录保存失败，请重试。", 503)
    _practical_trial_cache[cache_key] = result
    return result


def submit_practical_task(
    db: Session,
    session: SessionRecord,
    task_id: str,
    source: str,
    language: str,
    explanation: str,
    request_id: str,
) -> tuple[InterviewRun, ExecutionResult, InterviewerPayload, int | None]:
    run = get_current_run(db, session)
    if not run:
        raise ServiceError("当前不在进行中的面试。", 409)
    # Check idempotency before checking the current task: a client may retry
    # after the server already advanced to the next question.
    existing = db.scalar(select(PracticalSubmission).where(PracticalSubmission.run_id == run.id, PracticalSubmission.request_id == request_id))
    if existing:
        if not existing.is_final:
            raise ServiceError("该 request_id 已用于公开试跑，请为最终提交生成新的 request_id。", 409)
        result = _execution_from_json(existing.result_json)
        latest = next((turn for turn in reversed(run.turns) if turn.role == "interviewer"), None)
        output = InterviewerPayload(
            question=latest.content if latest else "",
            topic=latest.topic or "" if latest else "",
            topic_index=latest.plan_topic_index if latest else None,
            done=run.status == "ready_for_feedback",
        )
        return run, result, output, latest.sequence if latest else None
    if run.status != "interview_in_progress":
        raise ServiceError("当前不在进行中的面试。", 409)
    _plan, index, topic, _current = _current_practical_topic(run, task_id)
    if language not in topic.language_options and not (topic.type == "practical" and topic.practical_type == "experiment_analysis" and language == "text"):
        raise ServiceError("当前实操题不支持该语言。", 422)
    if len(source.encode("utf-8")) > settings.practical_max_source_chars:
        raise ServiceError("代码或回答超过大小限制。", 422)
    if not source.strip() and topic.type != "code_review" and not (topic.type == "practical" and topic.practical_type == "experiment_analysis"):
        raise ServiceError("代码或 SQL 不能为空。", 422)
    locked = db.scalar(select(PracticalSubmission).where(PracticalSubmission.run_id == run.id, PracticalSubmission.task_id == task_id, PracticalSubmission.locked.is_(True)))
    if locked:
        raise ServiceError("本题已经提交并锁定，不能重复修改。", 409)
    if topic.type == "practical" and topic.practical_type == "experiment_analysis":
        _validate_analysis_source(source)
        result = ExecutionResult(status="ok", passed=1, total=1, public=False)
    elif topic.type == "code_review" and not source.strip():
        if not explanation.strip():
            raise ServiceError("代码理解题至少需要填写解释，修正版代码可选。", 422)
        result = ExecutionResult(status="not_executed", passed=0, total=0, runtime_error="未提交修正版，仅记录解释", public=False)
    else:
        try:
            result = runner_client.execute(topic.model_dump(), source, language, hidden=True)
        except RunnerError as exc:
            raise ServiceError(str(exc), 503) from exc
    sequence = max((turn.sequence for turn in run.turns), default=0) + 1
    submission = PracticalSubmission(
        run_id=run.id,
        task_id=task_id,
        turn_sequence=sequence,
        task_type=topic.type if topic.type != "practical" else (topic.practical_type or topic.type),
        language=language,
        source=source,
        explanation=explanation.strip() or None,
        result_json=_json(result.as_dict()),
        is_final=True,
        locked=True,
        request_id=request_id,
    )
    db.add(submission)
    db.flush()
    if topic.type == "practical" and topic.practical_type == "experiment_analysis":
        summary = f"实操题《{topic.title}》最终提交（{language}）：结构化分析已记录，无需代码执行。"
    else:
        summary = f"实操题《{topic.title}》最终提交（{language}）：通过 {result.passed}/{result.total} 个测试。"
        if result.compile_error:
            summary += f" 编译错误：{result.compile_error[:500]}"
        elif result.runtime_error:
            summary += f" 运行结果：{result.runtime_error[:500]}"
    if explanation.strip():
        summary += f" 候选人说明：{explanation.strip()[:2000]}"
    metadata = {"submission_id": submission.id, "task_id": task_id, "result": result.as_dict(), "language": language}
    try:
        _run, output, next_sequence = answer_interview(
            db,
            session,
            summary,
            request_id,
            turn_kind=topic.type,
            task_id=task_id,
            metadata=metadata,
            force_next_topic=True,
        )
    except Exception:
        db.rollback()
        raise
    return run, result, output, next_sequence


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
    practical_evidence = []
    for submission in run.practical_submissions:
        if not submission.is_final:
            continue
        try:
            result = json.loads(submission.result_json)
        except json.JSONDecodeError:
            result = {}
        practical_evidence.append(
            f"实操题 {submission.task_id}（{submission.task_type}/{submission.language or 'text'}）："
            f"通过 {result.get('passed', 0)}/{result.get('total', 0)}，"
            f"状态 {result.get('status', 'unknown')}，"
            f"候选人最终提交：{submission.source[:600]}"
            + (f"；说明：{submission.explanation[:600]}" if submission.explanation else "")
        )
    if practical_evidence:
        transcript += "\n" + "\n".join(practical_evidence)
    observations = "\n".join(f"第{o.turn_sequence}轮：{o.evidence}" for o in run.observations)
    assessment = _model_json(
        provider(),
        FEEDBACK_SYSTEM,
        FEEDBACK_USER.format(
            profile=profile.candidate_profile_json if profile else "{}",
            plan=_public_plan_json(run.plan_json),
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
