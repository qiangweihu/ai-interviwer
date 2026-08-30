from __future__ import annotations

import asyncio
import hashlib
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import InterviewRun, Profile, SessionRecord, cleanup_expired, get_db, init_db, utcnow
from .interviewer_styles import catalog, public_style
from .schemas import (
    AnswerRequest,
    AnswerResponse,
    FeedbackResponse,
    InterviewerStyleCatalog,
    InterviewStateResponse,
    PlanRequest,
    SessionResponse,
    StartResponse,
)
from .services import (
    ServiceError,
    answer_interview,
    create_plan,
    end_interview,
    generate_feedback,
    get_current_run,
    new_session,
    profile_from_upload,
    start_new_round,
    start_interview,
    style_for_session,
    style_for_run,
)


COOKIE_NAME = "interview_session"


class ModelRateLimiter:
    def __init__(self):
        self.hits: dict[str, list[datetime]] = {}

    def allow(self, key: str) -> bool:
        now = datetime.utcnow()
        cutoff = now - timedelta(hours=1)
        recent = [item for item in self.hits.get(key, []) if item > cutoff]
        if len(recent) >= settings.max_model_calls_per_hour:
            self.hits[key] = recent
            return False
        recent.append(now)
        self.hits[key] = recent
        return True


limiter = ModelRateLimiter()


async def _cleanup_loop():
    while True:
        await asyncio.sleep(3600)
        db = next(get_db())
        try:
            cleanup_expired(db)
        finally:
            db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    db = next(get_db())
    try:
        cleanup_expired(db)
    finally:
        db.close()
    task = asyncio.create_task(_cleanup_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="AI 科研模拟面试官", version="1.0.0", lifespan=lifespan)


def _service_error(exc: ServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


def current_session(request: Request, db: Session = Depends(get_db)) -> SessionRecord:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="会话不存在，请先创建会话。")
    digest = hashlib.sha256(token.encode()).hexdigest()
    record = db.scalar(select(SessionRecord).where(SessionRecord.token_hash == digest))
    if not record or record.expires_at < utcnow():
        raise HTTPException(status_code=401, detail="会话已过期，请重新开始。")
    return record


def _preview(run: InterviewRun | None) -> dict | None:
    if not run or not run.plan_json:
        return None
    import json

    plan = json.loads(run.plan_json)
    return {
        "duration_minutes": plan.get("duration_minutes", 25),
        "main_question_count": plan.get("main_question_count", 10),
        "topics": [{"title": item.get("title"), "objective": item.get("objective"), "minutes": item.get("minutes")} for item in plan.get("topics", [])],
        "research_status": run.research_status,
    }


def _session_style(session: SessionRecord, run: InterviewRun | None = None) -> dict:
    return public_style(style_for_run(run) if run and run.interviewer_style_json else style_for_session(session))


def _session_response(session: SessionRecord, db: Session, run: InterviewRun | None = None) -> SessionResponse:
    run = run if run is not None else get_current_run(db, session)
    return SessionResponse(
        status=session.status,
        profile_revision=session.profile_revision,
        plan_profile_revision=run.plan_profile_revision if run else None,
        current_run_id=run.id if run else None,
        expires_at=session.expires_at,
        profile_complete=db.get(Profile, session.id) is not None,
        plan_preview=_preview(run),
        interviewer_style=_session_style(session, run),
    )


@app.exception_handler(ServiceError)
async def handle_service_error(_request: Request, exc: ServiceError):
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


@app.get("/health")
def health():
    return {"status": "ok", "service": "ai-interviwer"}


@app.get("/api/interviewer-styles", response_model=InterviewerStyleCatalog)
def interviewer_styles():
    return catalog()


@app.post("/api/session", response_model=SessionResponse)
def create_api_session(response: Response, db: Session = Depends(get_db)):
    record, token = new_session(db)
    response.set_cookie(COOKIE_NAME, token, max_age=settings.session_ttl_hours * 3600, httponly=True, samesite="lax", secure=settings.cookie_secure, path="/")
    return _session_response(record, db)


@app.get("/api/session", response_model=SessionResponse)
def read_api_session(session: SessionRecord = Depends(current_session), db: Session = Depends(get_db)):
    return _session_response(session, db)


@app.delete("/api/session")
def delete_api_session(response: Response, session: SessionRecord = Depends(current_session), db: Session = Depends(get_db)):
    db.delete(session)
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"status": "deleted"}


@app.post("/api/session/new", response_model=SessionResponse)
def new_api_round(session: SessionRecord = Depends(current_session), db: Session = Depends(get_db)):
    try:
        start_new_round(db, session)
    except ServiceError as exc:
        raise _service_error(exc)
    return _session_response(session, db)


@app.post("/api/profile", response_model=SessionResponse)
def upload_profile(
    request: Request,
    direction: str = Form(""),
    target_group: str = Form("待确认"),
    target_program: str = Form("待确认"),
    resume: UploadFile = File(...),
    session: SessionRecord = Depends(current_session),
    db: Session = Depends(get_db),
):
    try:
        content = resume.file.read(settings.max_resume_bytes + 1)
        profile_from_upload(db, session, direction, target_group, target_program, resume.filename or "resume.txt", content)
    except ServiceError as exc:
        raise _service_error(exc)
    return _session_response(session, db)


@app.post("/api/plan", response_model=SessionResponse)
def build_plan(request: Request, body: PlanRequest | None = None, session: SessionRecord = Depends(current_session), db: Session = Depends(get_db)):
    if not limiter.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试。")
    try:
        run = create_plan(db, session, body.interviewer_style if body else None)
    except ServiceError as exc:
        raise _service_error(exc)
    return _session_response(session, db, run)


@app.post("/api/interview/start", response_model=StartResponse)
def begin_interview(request: Request, session: SessionRecord = Depends(current_session), db: Session = Depends(get_db)):
    if not limiter.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试。")
    try:
        _run, question, topic, sequence = start_interview(db, session)
    except ServiceError as exc:
        raise _service_error(exc)
    return StartResponse(status=session.status, question=question, topic=topic, turn_sequence=sequence)


@app.get("/api/interview", response_model=InterviewStateResponse)
def read_interview_state(session: SessionRecord = Depends(current_session), db: Session = Depends(get_db)):
    run = get_current_run(db, session)
    if not run:
        raise HTTPException(status_code=404, detail="当前没有面试记录。")
    turns = [{"sequence": turn.sequence, "role": turn.role, "content": turn.content} for turn in run.turns if turn.role in {"interviewer", "candidate"}]
    latest = next((turn for turn in reversed(run.turns) if turn.role == "interviewer"), None)
    question = latest.content if run.status == "interview_in_progress" and latest else None
    return InterviewStateResponse(status=run.status, question=question, topic=latest.topic if question and latest else None, turn_sequence=latest.sequence if question and latest else None, turns=turns)


@app.post("/api/interview/answer", response_model=AnswerResponse)
def submit_answer(request: Request, body: AnswerRequest, session: SessionRecord = Depends(current_session), db: Session = Depends(get_db)):
    if not limiter.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=429, detail="本小时模型调用次数已达到匿名上限，请稍后再试。")
    try:
        _run, output, sequence = answer_interview(db, session, body.answer, body.request_id)
    except ServiceError as exc:
        raise _service_error(exc)
    return AnswerResponse(status=session.status, question=output.question or None, topic=output.topic or None, turn_sequence=sequence, done=output.done, clarification=output.clarification)


@app.post("/api/interview/end", response_model=SessionResponse)
def finish_interview(session: SessionRecord = Depends(current_session), db: Session = Depends(get_db)):
    try:
        run = end_interview(db, session)
    except ServiceError as exc:
        raise _service_error(exc)
    return _session_response(session, db, run)


@app.post("/api/feedback", response_model=FeedbackResponse)
def build_feedback(request: Request, session: SessionRecord = Depends(current_session), db: Session = Depends(get_db)):
    if not limiter.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试。")
    try:
        feedback = generate_feedback(db, session)
    except ServiceError as exc:
        raise _service_error(exc)
    return FeedbackResponse(status=session.status, feedback=feedback)


@app.get("/api/feedback", response_model=FeedbackResponse)
def read_feedback(request: Request, session: SessionRecord = Depends(current_session), db: Session = Depends(get_db)):
    if not limiter.allow(request.client.host if request.client else "unknown"):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试。")
    try:
        feedback = generate_feedback(db, session)
    except ServiceError as exc:
        raise _service_error(exc)
    return FeedbackResponse(status=session.status, feedback=feedback)


FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/{path:path}")
def frontend(path: str):
    if path.startswith("api/") or path == "health":
        raise HTTPException(status_code=404, detail="Not found")
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"service": "ai-interviwer", "message": "前端尚未构建，请运行 npm run build。"})
