from __future__ import annotations

"""One-shot worker executed inside a disposable runner container."""

import json
import os
import re
import resource
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


MAX_OUTPUT = 64 * 1024
MAX_SOURCE = 64 * 1024


def _limits(file_size: int = MAX_OUTPUT) -> None:
    # The container is the primary isolation boundary.  These limits are a
    # second line of defence if this worker is run in a development process.
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_size, file_size))
        # Docker's --pids-limit enforces this in production.  macOS rejects
        # lowering RLIMIT_NPROC for the compiler's posix_spawn path, so only
        # apply the process limit in the Linux fallback.
        if sys.platform.startswith("linux"):
            resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    except (OSError, ValueError):
        pass


def _clip(value: bytes | str | None) -> tuple[str, bool]:
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else (value or "")
    clipped = len(text.encode("utf-8")) > MAX_OUTPUT
    encoded = text.encode("utf-8")[:MAX_OUTPUT]
    return encoded.decode("utf-8", errors="replace"), clipped


def _safe_diagnostic(value: str, cwd: Path) -> str:
    """Keep compiler/runtime diagnostics useful without exposing temp paths."""

    sanitized = value.replace(str(cwd), "<source>")
    return re.sub(r"(?:/(?:tmp|opt|usr|home|var)/[^\s:'\"]+)", "<runner-path>", sanitized)


def _tests(payload: dict[str, Any]) -> list[dict[str, Any]]:
    tests = payload.get("tests") or []
    normalized: list[dict[str, Any]] = []
    for item in tests:
        if isinstance(item, dict):
            normalized.append(item)
    return normalized or [{"input": "", "output": ""}]


def _run_command(command: list[str], stdin: str, timeout: float, cwd: Path, *, file_size_limit: int = MAX_OUTPUT) -> tuple[int, str, str, bool, int]:
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1", "TMPDIR": str(cwd)},
            start_new_session=True,
            preexec_fn=(lambda: _limits(file_size_limit)) if os.name != "nt" else None,
        )
        try:
            stdout, stderr = process.communicate(stdin.encode("utf-8"), timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.kill()
            stdout, stderr = process.communicate()
            out, clipped = _clip(stdout)
            err, err_clipped = _clip(stderr)
            return 124, out, err or "运行超时", clipped or err_clipped, int((time.monotonic() - started) * 1000)
        out, clipped = _clip(stdout)
        err, err_clipped = _clip(stderr)
        return process.returncode, out, err, clipped or err_clipped, int((time.monotonic() - started) * 1000)
    except (OSError, ValueError) as exc:
        return 125, "", str(exc), False, int((time.monotonic() - started) * 1000)


def _run_program(payload: dict[str, Any]) -> dict[str, Any]:
    source = str(payload.get("source") or "")
    if not source.strip():
        return {"status": "failed", "total": len(_tests(payload)), "runtime_error": "代码不能为空"}
    if len(source.encode("utf-8")) > MAX_SOURCE:
        return {"status": "failed", "total": len(_tests(payload)), "runtime_error": "代码超过大小限制"}
    language = payload.get("language")
    tests = _tests(payload)
    overall_deadline = time.monotonic() + 15
    with tempfile.TemporaryDirectory(prefix="practical-job-") as temporary:
        cwd = Path(temporary)
        if language == "python":
            source_path = cwd / "main.py"
            source_path.write_text(source, encoding="utf-8")
            command = [sys.executable, "-I", str(source_path)]
        elif language == "cpp":
            source_path = cwd / "main.cpp"
            binary = cwd / "main"
            source_path.write_text(source, encoding="utf-8")
            compile_result = _run_command(["g++", "-std=c++20", "-O2", "-pipe", str(source_path), "-o", str(binary)], "", 10, cwd, file_size_limit=16 * 1024 * 1024)
            if compile_result[0] != 0:
                return {
                    "status": "failed",
                    "total": len(tests),
                    "compile_error": _safe_diagnostic(compile_result[2] or compile_result[1] or "编译失败", cwd),
                    "output_truncated": compile_result[3],
                    "execution_ms": compile_result[4],
                }
            command = [str(binary)]
        else:
            return {"status": "failed", "total": len(tests), "runtime_error": "不支持的执行语言"}

        passed = 0
        elapsed = 0
        truncated = False
        first_error = ""
        for test in tests:
            remaining = overall_deadline - time.monotonic()
            if remaining <= 0:
                return {
                    "status": "failed",
                    "passed": passed,
                    "total": len(tests),
                    "runtime_error": "运行超过单次任务总时限",
                    "output_truncated": truncated,
                    "execution_ms": elapsed,
                }
            code, output, error, was_truncated, duration = _run_command(command, str(test.get("input", "")), min(2, remaining), cwd)
            elapsed += duration
            truncated = truncated or was_truncated
            expected = str(test.get("output", "")).strip()
            if code == 0 and output.strip() == expected:
                passed += 1
            elif not first_error:
                first_error = "运行超时" if code == 124 else ("输出超过限制" if was_truncated else (_safe_diagnostic(error.strip(), cwd) or "输出与预期不一致"))
        return {
            "status": "ok" if passed == len(tests) else "failed",
            "passed": passed,
            "total": len(tests),
            "runtime_error": None if passed == len(tests) else first_error,
            "output_truncated": truncated,
            "execution_ms": elapsed,
        }


_DANGEROUS_SQL = re.compile(r"(?:;|\b(?:insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|load_extension)\b)", re.I)


def _run_sql(payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("source") or "").strip()
    tests = _tests(payload)
    if not query:
        return {"status": "failed", "total": len(tests), "runtime_error": "SQL 不能为空"}
    # A single trailing semicolon is normal SQL editor syntax; multiple
    # statements and semicolons inside the statement remain forbidden.
    if query.endswith(";"):
        query = query[:-1].rstrip()
    if _DANGEROUS_SQL.search(query) or not re.match(r"^(?:select|with)\b", query, re.I):
        return {"status": "failed", "total": len(tests), "runtime_error": "只允许只读 SELECT/CTE 查询"}
    materials = payload.get("materials") or {}
    connection = sqlite3.connect(":memory:")
    try:
        schema = materials.get("schema", "")
        seed = materials.get("seed", "")
        if schema:
            connection.executescript(str(schema))
        if seed:
            connection.executescript(str(seed))
        passed = 0
        output_truncated = False
        first_error = ""
        for test in tests:
            try:
                deadline = time.monotonic() + 2
                connection.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10000)
                cursor = connection.execute(query)
                rows: list[tuple[Any, ...]] = []
                encoded_size = 2
                while True:
                    batch = cursor.fetchmany(256)
                    if not batch:
                        break
                    rows.extend(batch)
                    encoded_size += len(json.dumps([list(row) for row in batch], ensure_ascii=False).encode("utf-8"))
                    if encoded_size > MAX_OUTPUT:
                        output_truncated = True
                        break
                connection.set_progress_handler(None, 0)
                if output_truncated:
                    if not first_error:
                        first_error = "输出超过限制"
                    continue
                expected_raw = test.get("rows", test.get("output", []))
                if isinstance(expected_raw, str):
                    expected = [list(row) for row in json.loads(expected_raw)]
                else:
                    expected = expected_raw
                actual = [list(row) for row in rows]
                if actual == expected:
                    passed += 1
                elif not first_error:
                    first_error = "查询结果与预期不一致"
            except (sqlite3.Error, ValueError, TypeError) as exc:
                if not first_error:
                    first_error = str(exc)
        return {
            "status": "ok" if passed == len(tests) and not output_truncated else "failed",
            "passed": passed,
            "total": len(tests),
            "runtime_error": None if passed == len(tests) and not output_truncated else first_error,
            "output_truncated": output_truncated,
        }
    finally:
        connection.close()


def execute(payload: dict[str, Any]) -> dict[str, Any]:
    task_type = payload.get("task_type")
    practical_type = payload.get("practical_type")
    if task_type == "practical" and practical_type == "sql":
        return _run_sql(payload)
    if task_type == "practical" and practical_type == "experiment_analysis":
        return {"status": "ok", "passed": 1, "total": 1, "runtime_error": None}
    return _run_program(payload)


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
        result = execute(payload)
    except Exception:  # keep the runner protocol JSON-only and path-free
        result = {"status": "failed", "passed": 0, "total": 0, "runtime_error": "执行器内部错误"}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
