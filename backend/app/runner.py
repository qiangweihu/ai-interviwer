from __future__ import annotations

"""Client for the private practical-task runner.

The application process never executes candidate code.  In production this
module talks to the internal runner HTTP service; mock mode is intentionally
deterministic so the fictional demo and unit tests do not need Docker.
"""

import json
import re
import time
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import Request, urlopen

from .config import settings


class RunnerError(RuntimeError):
    pass


@dataclass
class ExecutionResult:
    status: str = "failed"
    passed: int = 0
    total: int = 0
    compile_error: str | None = None
    runtime_error: str | None = None
    output_truncated: bool = False
    execution_ms: int | None = None
    public: bool = True

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "passed": self.passed,
            "total": self.total,
            "compile_error": self.compile_error,
            "runtime_error": self.runtime_error,
            "output_truncated": self.output_truncated,
            "execution_ms": self.execution_ms,
            "public": self.public,
        }


def _result_from_body(body: dict) -> ExecutionResult:
    defaults = ExecutionResult()
    values = {
        field: body.get(field, getattr(defaults, field))
        for field in ExecutionResult.__dataclass_fields__
    }
    # The runner is an internal service, but do not let malformed values
    # propagate into the public response model.
    if values["status"] not in {"ok", "failed", "unavailable", "not_executed"}:
        values["status"] = "failed"
    for field in ("passed", "total"):
        try:
            values[field] = max(0, int(values[field] or 0))
        except (TypeError, ValueError):
            values[field] = 0
    for field in ("compile_error", "runtime_error"):
        value = values[field]
        if value is not None:
            cleaned = re.sub(r"(?:/(?:tmp|opt|usr|home|var)/[^\s:'\"]+)", "<runner-path>", str(value))
            values[field] = cleaned[:4096]
    return ExecutionResult(**values)


class RunnerClient:
    def __init__(self):
        self.url = settings.practical_runner_url.rstrip("/")

    def health(self) -> bool:
        if not settings.practical_runner_enabled:
            return False
        if settings.mock_mimo:
            return True
        try:
            request = Request(f"{self.url}/health", method="GET")
            if settings.practical_runner_token:
                request.add_header("X-Runner-Token", settings.practical_runner_token)
            with urlopen(request, timeout=2) as response:
                return response.status == 200
        except (OSError, URLError):
            return False

    def execute(self, task: dict, source: str, language: str, *, hidden: bool) -> ExecutionResult:
        if not settings.practical_runner_enabled:
            raise RunnerError("实操题执行器尚未启用。")
        started = time.monotonic()
        if settings.mock_mimo:
            result = self._mock_execute(task, source, language, hidden=hidden)
            result.execution_ms = int((time.monotonic() - started) * 1000)
            result.public = not hidden
            return result
        payload = {
            "task_type": task.get("type", "coding"),
            "practical_type": task.get("practical_type"),
            "language": language,
            "source": source,
            "tests": task.get("hidden_tests", []) if hidden else [sample for sample in task.get("public_samples", [])],
            "materials": task.get("materials", {}),
            "hidden": hidden,
        }
        request = Request(
            f"{self.url}/run",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        if settings.practical_runner_token:
            request.add_header("X-Runner-Token", settings.practical_runner_token)
        try:
            with urlopen(request, timeout=18) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, ValueError) as exc:
            raise RunnerError("实操题执行器暂时不可用，请稍后重试。") from exc
        body["public"] = not hidden
        return _result_from_body(body)

    @staticmethod
    def _mock_execute(task: dict, source: str, language: str, *, hidden: bool) -> ExecutionResult:
        tests = task.get("hidden_tests", []) if hidden else task.get("public_samples", [])
        total = len(tests) or 1
        normalized = source.lower()
        if "while true" in normalized or "timeout" in normalized:
            return ExecutionResult(status="failed", total=total, runtime_error="运行超时")
        if "compile_error" in normalized or "syntax_error" in normalized or "语法错误" in source:
            return ExecutionResult(status="failed", total=total, compile_error="示例编译/语法错误")
        # Demo mode does not pretend to execute arbitrary user code.  It only
        # supplies stable evidence for the fictional workflow and marks an
        # explicitly labelled wrong submission as failed.
        passed = 0 if "wrong_answer" in normalized or "错误答案" in source else total
        return ExecutionResult(status="ok" if passed == total else "failed", passed=passed, total=total)


runner_client = RunnerClient()
