from __future__ import annotations

"""Private practical runner orchestrator.

Run this service in the separate ``runner`` Compose service.  It is the only
process allowed to access the Docker socket.  Each request is handed to a
one-shot worker container with no network and no host mounts.  For local
tests, ``RUNNER_USE_DOCKER=false`` uses the same worker in-process.
"""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException

from .runner_worker import execute as execute_local


app = FastAPI(title="AI interview practical runner", version="1.0.0")
RUNNER_TOKEN = os.getenv("PRACTICAL_RUNNER_TOKEN", "")
RUNNER_USE_DOCKER = os.getenv("RUNNER_USE_DOCKER", "true").lower() in {"1", "true", "yes"}
RUNNER_IMAGE = os.getenv("RUNNER_IMAGE", "ai-interviwer-runner:latest")
WORKER_PATH = os.getenv("RUNNER_WORKER_PATH", "/opt/backend/runner_worker.py")
RUNNER_MAX_CONCURRENCY = max(1, int(os.getenv("RUNNER_MAX_CONCURRENCY", "2")))
_RUNNER_SLOTS = threading.BoundedSemaphore(RUNNER_MAX_CONCURRENCY)


def _authorized(token: str | None) -> bool:
    return not RUNNER_TOKEN or token == RUNNER_TOKEN


def _docker_execute(payload: dict[str, Any]) -> dict[str, Any]:
    command = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,exec,nosuid,nodev,size=64m",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--security-opt",
        "seccomp=default",
        "--pids-limit",
        "64",
        "--memory",
        "256m",
        "--cpus",
        "1",
        # Source and stdout are capped by the worker. Keep enough file-size
        # headroom for a normal C++20 executable while still relying on the
        # read-only root and disposable tmpfs for filesystem isolation.
        "--ulimit",
        "fsize=16777216:16777216",
        "--ulimit",
        "nproc=64:64",
        "--user",
        "65534:65534",
        RUNNER_IMAGE,
        "python",
        WORKER_PATH,
    ]
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=18,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("实操题执行器暂时不可用") from exc
    if completed.returncode != 0:
        # Docker diagnostics can contain host paths, image details or socket
        # information. Keep those internal; the application only needs a
        # stable unavailable signal.
        raise RuntimeError("实操题执行器暂时不可用")
    try:
        result = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("执行器返回格式无效") from exc
    if not isinstance(result, dict):
        raise RuntimeError("执行器返回格式无效")
    return result


@app.get("/health")
def health() -> dict[str, str]:
    if RUNNER_USE_DOCKER:
        try:
            check = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2, check=False)
            if check.returncode != 0:
                raise HTTPException(status_code=503, detail="Docker runner 不可用")
        except (OSError, subprocess.TimeoutExpired):
            raise HTTPException(status_code=503, detail="Docker runner 不可用")
    return {"status": "ok", "service": "practical-runner"}


@app.post("/run")
def run(payload: dict[str, Any], x_runner_token: str | None = Header(default=None)) -> dict[str, Any]:
    if not _authorized(x_runner_token):
        raise HTTPException(status_code=401, detail="runner unauthorized")
    source = str(payload.get("source") or "")
    if len(source.encode("utf-8")) > 65536:
        raise HTTPException(status_code=422, detail="代码超过大小限制")
    if not _RUNNER_SLOTS.acquire(timeout=15):
        raise HTTPException(status_code=503, detail="实操题执行器排队已满，请稍后重试")
    try:
        result = _docker_execute(payload) if RUNNER_USE_DOCKER else execute_local(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        _RUNNER_SLOTS.release()
    result["public"] = not bool(payload.get("hidden"))
    return result
